/* Native bridge state machine. Kept separate so recovery is tested with fake ports. */
export class NativeBridge {
  constructor(runtime, { publish = () => {}, schedule = (callback, delay) => globalThis.setTimeout(callback, delay), cancel = id => globalThis.clearTimeout(id) } = {}) {
    this.runtime = runtime;
    this.publish = publish;
    this.schedule = schedule;
    this.cancel = cancel;
    this.port = null;
    this.pending = new Map();
    this.connecting = null;
    this.retry = null;
    this.attempts = 0;
    this.disposed = false;
    this.state = { state: "Disconnected", message: "Waiting for the desktop application.", ready: false };
  }

  status(state, message, ready = false) {
    if (this.state.state === state && this.state.message === message && this.state.ready === ready) return;
    this.state = { state, message, ready };
    this.publish({ event: "connection", connection: this.state });
  }

  retryLater() {
    if (this.disposed) return;
    if (this.retry) return;
    const seconds = Math.min(30, 2 ** Math.min(this.attempts++, 5));
    this.retry = this.schedule(() => {
      this.retry = null;
      this.ensureConnected().catch(() => {});
    }, seconds * 1000);
  }

  lost(port, detail) {
    if (this.port !== port) return;
    this.port = null;
    for (const request of this.pending.values()) {
      this.cancel(request.timer);
      request.reject(new Error(detail));
    }
    this.pending.clear();
    this.status("Connection Error", `${detail} Retrying automatically. Install or reopen SaveIt4U if this continues.`);
    this.retryLater();
  }

  raw(action, values = {}) {
    return new Promise((resolve, reject) => {
      const id = crypto.randomUUID();
      const timer = this.schedule(() => {
        this.pending.delete(id);
        reject(new Error("The application did not respond in time. Your downloads remain in the queue."));
      }, action === "inspect" ? 100_000 : 30_000);
      this.pending.set(id, { resolve, reject, timer });
      try { this.port.postMessage({ action, ...values, id }); }
      catch (error) { this.cancel(timer); this.pending.delete(id); reject(error); }
    });
  }

  ensureConnected() {
    if (this.disposed) return Promise.reject(new Error("Connection closed."));
    if (this.port && this.state.ready) return Promise.resolve(null);
    if (this.connecting) return this.connecting;
    this.status("Connecting", "Connecting to SaveIt4U on your computer…");
    const promise = (async () => {
      let port = this.port;
      if (!port) {
        port = this.runtime.connectNative("com.saveit4u.downloader");
        this.port = port;
        port.onMessage.addListener(message => {
          if (this.port !== port) return;
          if (message.event === "fatal") {
            this.lost(port, message.error || "The application could not start.");
            port.disconnect();
            return;
          }
          if (message.id && this.pending.has(message.id)) {
            const request = this.pending.get(message.id);
            this.pending.delete(message.id);
            this.cancel(request.timer);
            message.ok ? request.resolve(message.result) : request.reject(new Error(message.error || "Application request failed."));
          } else if (message.event) {
            if (message.event === "engine_error") this.status("Connection Error", `${message.error} Reconnecting automatically.`);
            if (message.event === "engine_status" && message.ready && !this.state.ready) this.status("Connected", "Connected to the desktop application.", true);
            this.publish(message);
          }
        });
        port.onDisconnect.addListener(() => this.lost(port, this.runtime.lastError?.message || "The application connection ended."));
      }
      const snapshot = await this.raw("hello");
      this.attempts = 0;
      if (this.retry) { this.cancel(this.retry); this.retry = null; }
      this.status(snapshot.ready ? "Connected" : "Connection Error", snapshot.ready ? "Connected automatically. Downloads run in the background." : "The application is missing a bundled component. Reinstall SaveIt4U.", snapshot.ready);
      this.publish({ event: "snapshot", snapshot });
      return snapshot;
    })();
    this.connecting = promise;
    promise.catch(error => {
      this.status("Connection Error", `${error.message} Retrying automatically.`);
      this.retryLater();
    }).finally(() => { if (this.connecting === promise) this.connecting = null; });
    return promise;
  }

  async send(action, values = {}) {
    const initial = await this.ensureConnected();
    if (action === "hello" && initial) return initial;
    if (!this.port) throw new Error(this.state.message || "The application disconnected. Reconnecting automatically.");
    return this.raw(action, values);
  }

  dispose() {
    this.disposed = true;
    if (this.retry) this.cancel(this.retry);
    this.retry = null;
    const port = this.port;
    this.port = null;
    port?.disconnect();
    for (const request of this.pending.values()) { this.cancel(request.timer); request.reject(new Error("Connection closed.")); }
    this.pending.clear();
  }
}
