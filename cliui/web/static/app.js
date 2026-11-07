(function () {
  "use strict";

  function showFatal(message) {
    var root = document.getElementById("root");
    if (!root) {
      return;
    }
    root.innerHTML =
      '<div style="max-width:720px;margin:80px auto;padding:24px;border-radius:16px;' +
      "background:#fff;border:1px solid #ffd4d4;color:#b33131;font-family:system-ui," +
      'sans-serif;line-height:1.7">' +
      "<strong>控制台加载失败</strong><br>" +
      String(message) +
      "</div>";
  }

  function startReload(button) {
    var label = button.textContent;
    button.disabled = true;
    button.textContent = "正在重新加载…";

    function restore(message) {
      button.disabled = false;
      button.textContent = label;
      if (message) {
        window.alert(message);
      }
    }

    function goHome() {
      var url = new URL(window.location.href);
      var app = url.searchParams.get("app");
      if (url.pathname === "/" && url.searchParams.has("cmd")) {
        // Node ids are positional and may shift after a reload, so do not
        // reload straight back into a command form.
        window.location.href =
          "/" + (app ? "?app=" + encodeURIComponent(app) : "");
        return;
      }
      window.location.reload();
    }

    fetch("/api/reload", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    })
      .then(function (response) {
        return response
          .json()
          .catch(function () {
            return {};
          })
          .then(function (body) {
            return { ok: response.ok, body: body };
          });
      })
      .then(function (result) {
        if (result.ok && result.body && result.body.status === 0) {
          goHome();
          return;
        }
        restore((result.body && result.body.msg) || "重新加载失败");
      })
      .catch(function (error) {
        restore("重新加载失败：" + (error && error.message ? error.message : error));
      });
  }

  // Delegated so the button keeps working after AMIS re-renders the topbar.
  document.addEventListener("click", function (event) {
    var target = event.target;
    var button = target && target.closest ? target.closest(".cliui-reload-btn") : null;
    if (!button || button.disabled) {
      return;
    }
    startReload(button);
  });

  function boot() {
    var holder = document.getElementById("cliui-page");
    if (!holder) {
      showFatal("缺少页面数据（#cliui-page）。");
      return;
    }

    var page;
    try {
      page = JSON.parse(holder.textContent || holder.innerHTML || "{}");
    } catch (error) {
      showFatal("页面 JSON 解析失败：" + error.message);
      return;
    }

    if (typeof amisRequire !== "function") {
      showFatal("AMIS SDK 没有加载成功，请确认 /static/amis/sdk.js 可访问。");
      return;
    }

    var amis = amisRequire("amis/embed");
    var amisLib = amisRequire("amis");
    if (amisLib && typeof amisLib.setDefaultLocale === "function") {
      try {
        amisLib.setDefaultLocale("zh-CN");
      } catch (error) {
        /* older SDKs do not support this call */
      }
    }

    try {
      window.cliuiInstance = amis.embed("#root", page, {}, {});
    } catch (error) {
      showFatal("AMIS 渲染失败：" + (error && error.message ? error.message : error));
      if (window.console) {
        console.error(error);
      }
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
