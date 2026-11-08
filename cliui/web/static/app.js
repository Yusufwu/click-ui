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

  // ------------------------------------------------------------ cron 人话解释
  // AMIS renders the cron field with class ``cliui-cron-input``; the helper
  // line below it is filled from the server-side ``describe_cron`` text.
  var describeTimers = new WeakMap();
  var describeSeq = new WeakMap();

  function cronField(node) {
    var input = null;
    if (node && node.tagName === "INPUT") {
      input = node;
    } else if (node && node.querySelector) {
      input = node.querySelector("input");
    }
    if (!input || !input.closest) {
      return null;
    }
    if (!input.closest(".cliui-cron-input")) {
      return null;
    }
    var item = input.closest(".cxd-Form-item");
    if (!item) {
      return null;
    }
    return { input: input, item: item };
  }

  function setCronHint(input, text, failed) {
    var field = cronField(input);
    if (!field) {
      return;
    }
    var hint = field.item.querySelector(".cliui-cron-hint");
    if (!hint) {
      if (!text) {
        return;
      }
      hint = document.createElement("div");
      hint.className = "cliui-cron-hint";
      field.item.appendChild(hint);
    }
    hint.textContent = text || "";
    hint.style.display = text ? "" : "none";
    if (failed) {
      hint.classList.add("cliui-cron-hint-error");
    } else {
      hint.classList.remove("cliui-cron-hint-error");
    }
  }

  function requestDescribe(input) {
    if (!input) {
      return;
    }
    var value = (input.value || "").trim();
    var seq = (describeSeq.get(input) || 0) + 1;
    describeSeq.set(input, seq);
    if (!value) {
      setCronHint(input, "");
      return;
    }
    fetch("/api/schedules/describe?cron=" + encodeURIComponent(value), {
      credentials: "same-origin",
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
        if (describeSeq.get(input) !== seq) {
          return;
        }
        var body = result.body || {};
        if (result.ok && body.status === 0 && body.data) {
          setCronHint(input, "人话解释：" + body.data.description);
          return;
        }
        setCronHint(input, body.msg || "Cron 表达式无法解析", true);
      })
      .catch(function () {
        if (describeSeq.get(input) === seq) {
          setCronHint(input, "");
        }
      });
  }

  function scheduleDescribe(input) {
    var timer = describeTimers.get(input);
    if (timer) {
      clearTimeout(timer);
    }
    describeTimers.set(
      input,
      setTimeout(function () {
        requestDescribe(input);
      }, 350)
    );
  }

  function refreshCronHints() {
    var nodes = document.querySelectorAll(".cliui-cron-input");
    Array.prototype.forEach.call(nodes, function (node) {
      var field = cronField(node);
      if (field) {
        requestDescribe(field.input);
      }
    });
  }

  function scanCronInputs() {
    Array.prototype.forEach.call(
      document.querySelectorAll(".cliui-cron-input"),
      function (node) {
        var field = cronField(node);
        if (field && !field.item.querySelector(".cliui-cron-hint")) {
          requestDescribe(field.input);
        }
      }
    );
  }

  var scanScheduled = false;
  function scheduleScan() {
    if (scanScheduled) {
      return;
    }
    scanScheduled = true;
    setTimeout(function () {
      scanScheduled = false;
      scanCronInputs();
    }, 120);
  }

  // Typing (and AMIS clearing) updates the hint after a short pause.
  ["input", "change"].forEach(function (name) {
    document.addEventListener(name, function (event) {
      var target = event.target;
      if (!target || target.tagName !== "INPUT" || !target.closest) {
        return;
      }
      if (!target.closest(".cliui-cron-input")) {
        return;
      }
      scheduleDescribe(target);
    });
  });

  // Preset tags set the value through AMIS ``setValue``, which does not emit
  // an input event, so re-read the field shortly after the click.
  document.addEventListener("click", function (event) {
    var target = event.target;
    var tag = target && target.closest ? target.closest(".cliui-preset-tag") : null;
    if (!tag) {
      return;
    }
    setTimeout(refreshCronHints, 300);
  });

  function watchCronInputs() {
    if (!document.body || typeof MutationObserver !== "function") {
      return;
    }
    new MutationObserver(scheduleScan).observe(document.body, {
      childList: true,
      subtree: true,
    });
    scheduleScan();
  }

  function boot() {
    var holder = document.getElementById("cliui-page");
    if (!holder) {
      showFatal("缺少页面数据（#cliui-page）。");
      return;
    }
    watchCronInputs();

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
