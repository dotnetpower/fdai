(function () {
  "use strict";
  var input = document.querySelector("[data-approval-search]");
  var cards = Array.from(document.querySelectorAll("[data-approval]"));
  function filter() {
    var query = input.value.trim().toLowerCase();
    var shown = 0;
    cards.forEach(function (card) {
      card.hidden = !card.textContent.toLowerCase().includes(query);
      if (!card.hidden) shown++;
    });
    document.querySelector("[data-approval-count]").textContent = shown + " of " + cards.length + " shown";
    document.querySelector("[data-approval-empty]").hidden = shown !== 0;
  }
  input.addEventListener("input", filter);
  document.querySelector("[data-clear-approvals]").addEventListener("click", function () {
    input.value = "";
    filter();
    input.focus();
  });
})();
