/* Shared client behaviour.
 *
 * The app renders on the server; this file only adds what HTML cannot do on its
 * own — the mobile drawer, toasts, modals and a small fetch helper that carries
 * the CSRF token. Every page works with JavaScript disabled apart from the AI
 * chat, which is inherently interactive.
 */
(function () {
  "use strict";

  /* ------------------------------------------------------------ helpers -- */
  function on(root, event, selector, handler) {
    root.addEventListener(event, function (e) {
      var target = e.target.closest(selector);
      if (target && root.contains(target)) handler(e, target);
    });
  }

  function csrfToken() {
    var input = document.querySelector('input[name="csrf_token"]');
    return input ? input.value : "";
  }

  window.fp = window.fp || {};

  window.fp.request = function (url, options) {
    options = options || {};
    var headers = Object.assign(
      { "Content-Type": "application/json", "X-CSRF-Token": csrfToken() },
      options.headers || {}
    );
    return fetch(url, {
      method: options.method || "GET",
      headers: headers,
      credentials: "same-origin",
      body: options.body ? JSON.stringify(options.body) : undefined
    }).then(function (response) {
      return response
        .json()
        .catch(function () {
          return {};
        })
        .then(function (data) {
          if (!response.ok) {
            var error = new Error(data.message || "הפעולה נכשלה");
            error.status = response.status;
            error.payload = data;
            throw error;
          }
          return data;
        });
    });
  };

  /* ------------------------------------------------------------- toasts -- */
  window.fp.toast = function (message, tone) {
    var host = document.getElementById("toast-host");
    if (!host) return;
    var node = document.createElement("div");
    node.className = "toast" + (tone ? " toast-" + tone : "");
    node.textContent = message;
    host.appendChild(node);
    setTimeout(function () {
      node.style.opacity = "0";
      setTimeout(function () {
        node.remove();
      }, 220);
    }, 3200);
  };

  /* ------------------------------------------------------------ drawers -- */
  function toggleDrawer(id, force) {
    var panel = document.getElementById(id);
    if (!panel) return;
    var backdrop = document.querySelector("[data-drawer-backdrop]");
    var isOpen = panel.classList.contains("is-open") || !panel.hidden;
    var open = typeof force === "boolean" ? force : !isOpen;

    if (panel.classList.contains("sidebar")) {
      panel.classList.toggle("is-open", open);
      if (backdrop) backdrop.hidden = !open;
    } else {
      panel.hidden = !open;
    }
    document.body.style.overflow = open && window.innerWidth < 1080 ? "hidden" : "";
  }

  on(document, "click", "[data-drawer-toggle]", function (e, target) {
    e.preventDefault();
    toggleDrawer(target.getAttribute("data-drawer-toggle"));
  });

  on(document, "click", "[data-drawer-backdrop]", function () {
    document.querySelectorAll(".sidebar.is-open").forEach(function (panel) {
      toggleDrawer(panel.id, false);
    });
  });

  /* ------------------------------------------------------------- modals -- */
  window.fp.openModal = function (id) {
    var modal = document.getElementById(id);
    if (modal) {
      modal.hidden = false;
      document.body.style.overflow = "hidden";
    }
  };
  window.fp.closeModal = function (modal) {
    if (modal) {
      modal.hidden = true;
      document.body.style.overflow = "";
    }
  };

  on(document, "click", "[data-modal-open]", function (e, target) {
    e.preventDefault();
    window.fp.openModal(target.getAttribute("data-modal-open"));
  });
  on(document, "click", "[data-modal-close]", function (e, target) {
    e.preventDefault();
    window.fp.closeModal(target.closest("[data-modal]"));
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      document.querySelectorAll("[data-modal]:not([hidden])").forEach(window.fp.closeModal);
      document.querySelectorAll(".sidebar.is-open").forEach(function (panel) {
        toggleDrawer(panel.id, false);
      });
    }
  });

  /* -------------------------------------------------- forms and filters -- */
  // Submit-once guard: a double click must not create two subscriptions.
  on(document, "submit", "form[data-guard]", function (e, form) {
    if (form.dataset.submitted === "1") {
      e.preventDefault();
      return;
    }
    form.dataset.submitted = "1";
    var button = form.querySelector('button[type="submit"]');
    if (button) {
      button.disabled = true;
      button.classList.add("is-loading");
    }
  });

  // Filter selects that submit their form on change.
  on(document, "change", "[data-autosubmit]", function (e, control) {
    var form = control.closest("form");
    if (form) form.submit();
  });

  // Flash messages passed as a query parameter, rendered without reload noise.
  var params = new URLSearchParams(window.location.search);
  if (params.get("flash")) {
    window.fp.toast(params.get("flash"), params.get("tone") || "success");
    params.delete("flash");
    params.delete("tone");
    var query = params.toString();
    history.replaceState({}, "", window.location.pathname + (query ? "?" + query : ""));
  }

  /* -------------------------------------------------- optimistic toggles -- */
  on(document, "change", "[data-toggle-url]", function (e, input) {
    var row = input.closest(".list-row");
    if (row) row.classList.toggle("is-checked", input.checked);
    window.fp
      .request(input.getAttribute("data-toggle-url"), {
        method: "POST",
        body: { checked: input.checked }
      })
      .catch(function (error) {
        input.checked = !input.checked;
        if (row) row.classList.toggle("is-checked", input.checked);
        window.fp.toast(error.message, "error");
      });
  });
})();
