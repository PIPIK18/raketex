(() => {
  const list = document.getElementById("contact-editor-links");
  const add = document.getElementById("add-contact-link");
  const status = document.getElementById("contact-editor-status");
  add.addEventListener("click", () => {
    if (list.children.length >= 30) {
      status.textContent = "You can add up to 30 links.";
      return;
    }
    list.append(document.getElementById("contact-link-template").content.cloneNode(true));
    list.lastElementChild.querySelector("input").focus();
    status.textContent = "Link added.";
  });
  list.addEventListener("click", (event) => {
    const button = event.target.closest("[data-remove-link]");
    if (!button) return;
    const row = button.closest(".contact-editor-row");
    const next = row.nextElementSibling || row.previousElementSibling;
    row.remove();
    (next?.querySelector("input") || add).focus();
    status.textContent = "Link removed. Save to apply your changes.";
  });
})();
