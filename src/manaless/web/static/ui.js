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

  // --- 1a. swap modal (category-matched suggestions) ---------------------
  var swapModal = document.getElementById("swapmodal");

  function openSwap() {
    if (swapModal) swapModal.hidden = false;
  }
  function closeSwap() {
    if (!swapModal) return;
    swapModal.hidden = true;
    var body = document.getElementById("swapmodal-body");
    if (body) body.innerHTML = ""; // drop stale suggestions so the next open is fresh
  }

  document.addEventListener("click", function (e) {
    if (!e.target.closest) return;
    if (e.target.closest(".swap-open")) {
      openSwap(); // HTMX loads #swapmodal-body concurrently via the button's hx-get
      return;
    }
    // Close on the ✕ or a backdrop click (but not clicks inside the panel).
    if (swapModal && !swapModal.hidden &&
        (e.target.closest(".swapmodal-close") || e.target === swapModal)) {
      closeSwap();
      return;
    }
    var img = e.target.closest("#cardlist .card img");
    if (img) {
      openModal(img.getAttribute("src"), img.getAttribute("alt"));
      return;
    }
    if (modal && !modal.hidden && e.target.closest("#cardmodal")) closeModal();
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      closeModal();
      closeSwap();
    }
  });
  // A successful swap (suggestion submit, or autocomplete choose -> requestSubmit)
  // refreshes the board via OOB swaps; close the modal once it lands.
  document.body.addEventListener("htmx:afterRequest", function (e) {
    if (e.detail && e.detail.successful && e.target.closest &&
        e.target.closest("#swapmodal")) {
      closeSwap();
    }
  });

  // --- 1c. combo outlines -------------------------------------------------
  // Each combo present in the deck gets a colour; every card in that combo gets a
  // ring in it (stacked outward, so a card in N combos shows N rings). The combo
  // data rides in with the lazily-loaded readouts panel (#combo-data), so we re-run
  // on every htmx settle: after an edit the card list re-renders bare, then the
  // readouts refetch lands and re-draws the outlines.
  var COMBO_COLORS = ["#ff79c6", "#ffb86c", "#bd93f9", "#8be9fd", "#50fa7b", "#f1fa8c"];

  function comboKey(name) {
    // Front-face, case-folded — matches how the deck reconciles DFC/combo names.
    return (name || "").split("//")[0].trim().toLowerCase();
  }

  function applyComboOutlines() {
    var cards = document.querySelectorAll("#cardlist .card");
    cards.forEach(function (card) {
      card.style.boxShadow = "";
      if (card.classList.contains("in-combo")) {
        card.classList.remove("in-combo");
        card.removeAttribute("title");
      }
    });
    var dataEl = document.getElementById("combo-data");
    if (!dataEl) return;
    var combos;
    try {
      combos = JSON.parse(dataEl.textContent || "[]");
    } catch (err) {
      return;
    }
    var byName = {}; // front-face key -> [{color, combo}]
    combos.forEach(function (combo, i) {
      var color = COMBO_COLORS[i % COMBO_COLORS.length];
      var dot = document.querySelector('.combo-line[data-combo-index="' + i + '"] .combo-dot');
      if (dot) dot.style.background = color;
      (combo.cards || []).forEach(function (name) {
        var key = comboKey(name);
        (byName[key] || (byName[key] = [])).push({ color: color, combo: combo });
      });
    });
    cards.forEach(function (card) {
      var hits = byName[comboKey(card.getAttribute("data-name"))];
      if (!hits || !hits.length) return;
      card.style.boxShadow = hits
        .slice(0, 4) // cap the rings so they never spill into neighbouring cards
        .map(function (h, idx) {
          return "0 0 0 " + 2 * (idx + 1) + "px " + h.color;
        })
        .join(", ");
      card.classList.add("in-combo");
      card.title =
        "In combo:\n" +
        hits
          .map(function (h) {
            var line = (h.combo.cards || []).join(" + ");
            if (h.combo.produces && h.combo.produces.length) {
              line += " → " + h.combo.produces.join(", ");
            }
            return line;
          })
          .join("\n");
    });
  }

  document.body.addEventListener("htmx:afterSettle", applyComboOutlines);

  // --- 1b. hover card preview (palette add buttons) ----------------------
  var preview = document.getElementById("cardpreview");

  function positionPreview(e) {
    if (!preview || preview.hidden) return;
    var w = preview.offsetWidth || 300;
    // Prefer the left of the cursor (palette sits on the right edge); flip if tight.
    var left = e.clientX - w - 18;
    if (left < 8) left = e.clientX + 18;
    var top = Math.min(e.clientY - 40, window.innerHeight - (preview.offsetHeight || 400) - 8);
    preview.style.left = window.scrollX + Math.max(8, left) + "px";
    preview.style.top = window.scrollY + Math.max(8, top) + "px";
  }

  document.addEventListener("mouseover", function (e) {
    var el = e.target.closest ? e.target.closest("[data-img]") : null;
    if (!el || !preview) return;
    preview.querySelector("img").src = el.getAttribute("data-img");
    preview.hidden = false;
    positionPreview(e);
  });
  document.addEventListener("mousemove", positionPreview);
  document.addEventListener("mouseout", function (e) {
    var el = e.target.closest ? e.target.closest("[data-img]") : null;
    if (el && preview && !el.contains(e.relatedTarget)) {
      preview.hidden = true;
      preview.querySelector("img").src = "";
    }
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
