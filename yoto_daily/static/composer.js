/* The composer: show one panel at a time, and keep the hidden ones out of
 * the submission. Two panels share the field name "url", so disabling the
 * hidden inputs matters -- otherwise the wrong one wins. */

(function () {
  "use strict";

  var form = document.querySelector(".composer");
  if (!form) return;

  var panels = Array.prototype.slice.call(form.querySelectorAll(".panel"));
  var kinds = Array.prototype.slice.call(form.querySelectorAll('input[name="kind"]'));
  var types = Array.prototype.slice.call(form.querySelectorAll('input[name="type"]'));
  var kindChooser = form.querySelector(".chooser-nested");

  function checked(list) {
    for (var i = 0; i < list.length; i++) {
      if (list[i].checked) return list[i].value;
    }
    return null;
  }

  function show(name) {
    panels.forEach(function (panel) {
      var wanted = panel.getAttribute("data-panel") === name;
      panel.style.display = wanted ? "block" : "none";
      // Keep hidden fields from being submitted.
      Array.prototype.slice.call(panel.querySelectorAll("input, select, textarea")).forEach(
        function (input) {
          input.disabled = !wanted;
        }
      );
    });
  }

  function sync() {
    var type = checked(types);
    if (type === "file" || type === "stream") {
      if (kindChooser) kindChooser.hidden = true;
      show(type);
      return;
    }
    if (kindChooser) kindChooser.hidden = false;
    show(checked(kinds) || "music");
  }

  types.concat(kinds).forEach(function (input) {
    input.addEventListener("change", sync);
  });

  sync();
})();
