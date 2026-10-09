(() => {
  const id = "saveit4u-download-button";
  let previous = "";
  function update() {
    if (location.href === previous) return;
    previous = location.href;
    document.getElementById(id)?.remove();
    const valid = (location.pathname === "/watch" && /^[A-Za-z0-9_-]{11}$/.test(new URL(location.href).searchParams.get("v") || "")) ||
      /^\/shorts\/[A-Za-z0-9_-]{11}\/?$/.test(location.pathname);
    if (!valid) return;
    const button = document.createElement("button");
    button.id = id;
    button.type = "button";
    button.textContent = "↓ SaveIt4U";
    button.title = "Choose video quality, audio or transcript";
    button.addEventListener("click", () => {
      chrome.runtime.sendMessage({ action: "open_manager", url: location.href }).catch(() => {
        button.textContent = "Reload page to reconnect";
      });
    });
    document.body.append(button);
  }
  document.addEventListener("yt-navigate-finish", update);
  window.addEventListener("popstate", update);
  setInterval(update, 1500);
  update();
})();
