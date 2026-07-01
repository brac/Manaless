/* Builder client behaviours, framework-free and delegation-based so they keep
 * working after HTMX swaps #cardlist:
 *   1. Full-size card-image modal on click (E1).
 *   2. Type-ahead autocomplete for any [data-autocomplete] input (E5/E6).
 */
(function () {
  "use strict";

  // --- 1. card image modal (E1) ------------------------------------------
  var modal = document.getElementById("cardmodal");

  function openModal(src, alt) {
    if (!modal) return;
    var img = modal.querySelector("img");
    img.src = src;
    img.alt = alt || "";
    modal.hidden = false;
  }
  function closeModal() {
    if (!modal) return;
    modal.hidden = true;
    modal.querySelector("img").src = "";
  }

  document.addEventListener("click", function (e) {
    var img = e.target.closest ? e.target.closest("#cardlist .card img") : null;
    if (img) {
      openModal(img.getAttribute("src"), img.getAttribute("alt"));
      return;
    }
    if (modal && !modal.hidden && e.target.closest("#cardmodal")) closeModal();
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closeModal();
  });

  // --- 2. autocomplete (E5/E6) -------------------------------------------
  var box = document.createElement("ul");
  box.className = "ac-menu";
  box.hidden = true;
  document.body.appendChild(box);

  var active = null; // the input the menu is currently bound to
  var items = []; // current suggestion strings
  var cursor = -1; // highlighted index
  var seq = 0; // request generation, so a stale fetch can't clobber a newer one
  var timer = null;

  function hide() {
    box.hidden = true;
    box.innerHTML = "";
    items = [];
    cursor = -1;
    active = null;
  }

  function place(input) {
    var r = input.getBoundingClientRect();
    box.style.left = window.scrollX + r.left + "px";
    box.style.top = window.scrollY + r.bottom + "px";
    box.style.minWidth = r.width + "px";
  }

  function render() {
    box.innerHTML = "";
    items.forEach(function (name, i) {
      var li = document.createElement("li");
      li.textContent = name;
      li.className = i === cursor ? "on" : "";
      li.addEventListener("mousedown", function (ev) {
        ev.preventDefault(); // keep focus so the form submit sees the value
        choose(i);
      });
      box.appendChild(li);
    });
    box.hidden = items.length === 0;
  }

  function choose(i) {
    if (!active || i < 0 || i >= items.length) return;
    active.value = items[i];
    var form = active.form;
    hide();
    if (form && form.requestSubmit) form.requestSubmit();
    else if (form) form.submit();
  }

  function fetchFor(input) {
    var q = input.value.trim();
    var kind = input.getAttribute("data-autocomplete") || "card";
    if (q.length < 2) {
      hide();
      return;
    }
    var mine = ++seq;
    var url =
      "/api/autocomplete?kind=" +
      encodeURIComponent(kind) +
      "&q=" +
      encodeURIComponent(q);
    fetch(url)
      .then(function (r) {
        return r.ok ? r.json() : [];
      })
      .then(function (data) {
        if (mine !== seq || document.activeElement !== input) return;
        active = input;
        items = Array.isArray(data) ? data : [];
        cursor = -1;
        place(input);
        render();
      })
      .catch(function () {
        /* offline / rate-limited: just no suggestions */
      });
  }

  document.addEventListener("input", function (e) {
    var input = e.target;
    if (!input.matches || !input.matches("input[data-autocomplete]")) return;
    clearTimeout(timer);
    timer = setTimeout(function () {
      fetchFor(input);
    }, 150);
  });

  document.addEventListener("keydown", function (e) {
    if (box.hidden || !active || active !== e.target) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      cursor = Math.min(cursor + 1, items.length - 1);
      render();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      cursor = Math.max(cursor - 1, 0);
      render();
    } else if (e.key === "Enter") {
      if (cursor >= 0) {
        e.preventDefault();
        choose(cursor);
      }
    } else if (e.key === "Escape") {
      hide();
    }
  });

  document.addEventListener("focusout", function (e) {
    if (e.target === active) setTimeout(hide, 120); // let a click land first
  });
  window.addEventListener("resize", hide);
})();
