(function () {
  "use strict";

  var PREFIX = "claims-checklist:";
  var CONFETTI_COLORS = ["#7c4dff", "#00bfa5", "#ffab00", "#ff4081", "#2979ff"];

  function itemText(box) {
    var item = box.closest("li");
    return ((item ? item.textContent : "") || "").trim().replace(/\s+/g, " ").slice(0, 200);
  }

  function storageKey(box) {
    return PREFIX + location.pathname + "|" + itemText(box);
  }

  function checklistBoxes() {
    return Array.prototype.slice.call(
      document.querySelectorAll(".md-typeset .task-list-item input[type='checkbox']")
    );
  }

  function allChecked(boxes) {
    return boxes.length > 0 && boxes.every(function (box) {
      return box.checked;
    });
  }

  function injectStyles() {
    if (document.getElementById("claims-celebration-style")) {
      return;
    }
    var style = document.createElement("style");
    style.id = "claims-celebration-style";
    style.textContent = [
      ".claims-celebration{position:fixed;inset:0;pointer-events:none;z-index:10000;overflow:hidden}",
      ".claims-celebration__banner{position:absolute;top:35%;left:50%;padding:1rem 1.5rem;border-radius:.5rem;background:#1e1e2e;color:#fff;font-size:1.2rem;font-weight:600;box-shadow:0 8px 24px rgba(0,0,0,.35);animation:claims-pop .6s ease-out both}",
      ".claims-celebration__piece{position:absolute;top:-16px;width:10px;height:14px;border-radius:2px;animation-name:claims-fall;animation-timing-function:linear;animation-fill-mode:forwards}",
      "@keyframes claims-pop{from{transform:translate(-50%,-50%) scale(.6);opacity:0}to{transform:translate(-50%,-50%) scale(1);opacity:1}}",
      "@keyframes claims-fall{to{transform:translateY(110vh) rotate(720deg)}}",
      "@media (prefers-reduced-motion: reduce){.claims-celebration__piece{display:none}.claims-celebration__banner{animation:none;transform:translate(-50%,-50%)}}"
    ].join("");
    document.head.appendChild(style);
  }

  function celebrate() {
    injectStyles();
    var previous = document.querySelector(".claims-celebration");
    if (previous) {
      previous.remove();
    }

    var overlay = document.createElement("div");
    overlay.className = "claims-celebration";
    overlay.setAttribute("role", "status");

    var banner = document.createElement("div");
    banner.className = "claims-celebration__banner";
    banner.textContent = "🎉 All checklist items complete!";
    overlay.appendChild(banner);

    for (var i = 0; i < 90; i++) {
      var piece = document.createElement("span");
      piece.className = "claims-celebration__piece";
      piece.style.left = Math.random() * 100 + "vw";
      piece.style.background = CONFETTI_COLORS[i % CONFETTI_COLORS.length];
      piece.style.animationDuration = 2 + Math.random() * 2 + "s";
      piece.style.animationDelay = Math.random() * 0.6 + "s";
      overlay.appendChild(piece);
    }

    document.body.appendChild(overlay);
    setTimeout(function () {
      overlay.remove();
    }, 4500);
  }

  function restore() {
    document.querySelectorAll(".md-typeset input[type='checkbox']").forEach(function (box) {
      if (box.dataset.checklistBound === "true") {
        return;
      }
      box.dataset.checklistBound = "true";

      var saved = localStorage.getItem(storageKey(box));
      if (saved !== null) {
        box.checked = saved === "1";
      }

      box.addEventListener("change", function () {
        localStorage.setItem(storageKey(box), box.checked ? "1" : "0");
        if (box.checked && allChecked(checklistBoxes())) {
          celebrate();
        }
      });
    });
  }

  document$.subscribe(restore);
})();
