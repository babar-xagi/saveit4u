import test from "node:test";
import assert from "node:assert/strict";
import { NativeBridge } from "../extension/connection.js";

function event() {
  const handlers = [];
  return { addListener: fn => handlers.push(fn), fire: value => handlers.forEach(fn => fn(value)) };
}
function fixture() {
  const ports = [], messages = [], timers = new Map(), states = [];
  let next = 0;
  const runtime = { connectNative() {
    const port = { onMessage: event(), onDisconnect: event(), postMessage: message => messages.push({ port, message }), disconnect() { this.onDisconnect.fire(); } };
    ports.push(port); return port;
  } };
  const bridge = new NativeBridge(runtime, { publish: event => states.push(event),
    schedule: (callback, delay) => { const id = ++next; timers.set(id, { callback, delay }); return id; }, cancel: id => timers.delete(id) });
  return { bridge, runtime, ports, messages, timers, states };
}
const tick = () => new Promise(resolve => setImmediate(resolve));

test("connects once for concurrent requests and recovers after a native disconnect", async () => {
  const f = fixture();
  const first = f.bridge.ensureConnected();
  const second = f.bridge.ensureConnected();
  assert.equal(first, second);
  assert.equal(f.ports.length, 1);
  const hello = f.messages[0].message;
  f.ports[0].onMessage.fire({ id: hello.id, ok: true, result: { ready: true, jobs: [] } });
  await first; await tick();
  assert.equal(f.bridge.state.state, "Connected");
  const inspection = f.bridge.send("inspect", { url: "https://www.youtube.com/watch?v=jNQXAC9IVRw" });
  await tick();
  f.runtime.lastError = { message: "Pipe closed" };
  f.ports[0].onDisconnect.fire();
  await assert.rejects(inspection, /Pipe closed/);
  assert.equal(f.bridge.state.state, "Connection Error");
  assert.match(f.bridge.state.message, /Retrying automatically/);
  const retry = [...f.timers.values()].find(timer => timer.delay === 1000);
  assert.ok(retry); retry.callback();
  await tick();
  assert.equal(f.ports.length, 2);
  const reconnect = f.messages.at(-1).message;
  f.ports[1].onMessage.fire({ id: reconnect.id, ok: true, result: { ready: true, jobs: [{ id: "preserved" }] } });
  await tick();
  assert.equal(f.bridge.state.state, "Connected");
  assert.ok(f.states.some(item => item.event === "snapshot" && item.snapshot.jobs?.[0]?.id === "preserved"));
  f.bridge.dispose();
});

test("ignores stale-port events and reports bundled-component errors", async () => {
  const f = fixture();
  const promise = f.bridge.ensureConnected();
  f.ports[0].onMessage.fire({ id: f.messages[0].message.id, ok: true, result: { ready: false } });
  await promise; await tick();
  assert.equal(f.bridge.state.state, "Connection Error");
  f.bridge.dispose();
  f.ports[0].onMessage.fire({ event: "engine_status", ready: true });
  assert.equal(f.bridge.state.ready, false);
});
