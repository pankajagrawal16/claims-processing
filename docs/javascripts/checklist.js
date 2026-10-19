(function () {
  "use strict";

  var PREFIX = "claims-checklist:";

  function itemText(box) {
    var item = box.closest("li");
    return ((item ? item.textContent : "") || "").trim().replace(/\s+/g, " ").slice(0, 200);
  }

  function storageKey(box) {
    return PREFIX + location.pathname + "|" + itemText(box);
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
      });
    });
  }

  document$.subscribe(restore);
})();
