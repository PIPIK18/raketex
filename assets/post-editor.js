(() => {
  const form = document.getElementById("post-editor");
  const contentType = form.dataset.contentType || "post";
  const list = document.getElementById("segments");
  const fields = document.getElementById("editor-fields");
  const error = document.getElementById("editor-error");
  const status = document.getElementById("editor-status");
  let nextId = 0;
  let drag = null;
  let scrollFrame = null;

  const cards = () => Array.from(list.children);
  const announce = (message) => { status.textContent = message; };
  const showError = (message) => {
    error.textContent = message;
    error.hidden = false;
  };

  function refresh() {
    const items = cards();
    document.getElementById("segments-empty").hidden = items.length > 0;
    items.forEach((card, index) => {
      const label = `${index + 1}. ${card.dataset.type[0].toUpperCase() + card.dataset.type.slice(1)}`;
      card.querySelector(".segment-label").textContent = label;
      card.querySelector("[data-action='up']").disabled = index === 0;
      card.querySelector("[data-action='down']").disabled = index === items.length - 1;
      card.querySelector(".segment-handle").setAttribute("aria-label", `Drag ${label}; use arrow keys to move`);
    });
  }

  function move(card, direction) {
    const neighbor = direction < 0 ? card.previousElementSibling : card.nextElementSibling;
    if (!neighbor) return;
    if (direction < 0) list.insertBefore(card, neighbor);
    else list.insertBefore(neighbor, card);
    refresh();
    announce(`Segment moved to position ${cards().indexOf(card) + 1}.`);
  }

  function addSegment(item, focus = false) {
    if (cards().length >= 100) {
      showError(`A ${contentType} can contain up to 100 segments.`);
      return;
    }
    const id = `segment-${nextId++}`;
    const card = document.createElement("section");
    card.className = "segment";
    card.dataset.id = id;
    card.dataset.type = item.type;
    card.dataset.image = item.image_filename || item.video_filename || "";
    card.setAttribute("aria-labelledby", `${id}-label`);
    // Only static markup is inserted here; post content is assigned as text/value.
    card.innerHTML = `<div class="segment-header">
      <button type="button" class="segment-control segment-handle" title="Drag to reorder">&#10303;</button>
      <strong class="segment-label" id="${id}-label"></strong>
      <div class="segment-tools">
        <button type="button" class="segment-control" data-action="up" aria-label="Move segment up">&#8593;</button>
        <button type="button" class="segment-control" data-action="down" aria-label="Move segment down">&#8595;</button>
        <button type="button" class="segment-control segment-remove" data-action="remove" aria-label="Remove segment">remove</button>
      </div>
    </div><div class="field"></div>`;
    const field = card.querySelector(".field");
    const label = document.createElement("label");
    label.htmlFor = `${id}-content`;
    label.textContent = item.type;
    const input = document.createElement(item.type === "text" ? "textarea" : "input");
    input.id = label.htmlFor;
    input.required = true;
    field.append(label, input);
    if (item.type !== "text") {
      input.type = "file";
      input.name = `${item.type}_${id}`;
      input.accept = item.type === "video" ? ".mp4,.webm,.ogv" : ".png,.jpg,.jpeg,.gif,.webp";
      input.required = !card.dataset.image;
      const preview = document.createElement(item.type === "video" ? "video" : "img");
      if (item.type === "video") {
        preview.controls = true;
        preview.playsInline = true;
        preview.preload = "metadata";
      }
      preview.className = "image-preview";
      if (item.type === "image") preview.alt = "Segment image preview";
      else preview.setAttribute("aria-label", "Segment video preview");
      preview.draggable = false;
      if (item.image_src) {
        preview.src = item.image_src;
        preview.classList.add("visible");
      }
      field.append(preview);
      input.addEventListener("change", () => {
        card.uploaded = null;
        if (card.previewUrl) URL.revokeObjectURL(card.previewUrl);
        card.previewUrl = input.files[0] ? URL.createObjectURL(input.files[0]) : "";
        const src = card.previewUrl || item.image_src;
        if (src) preview.src = src;
        else preview.removeAttribute("src");
        preview.classList.toggle("visible", Boolean(src));
      });
    } else {
      input.value = item.text || "";
      input.placeholder = `Write this part of your ${contentType}...`;
    }
    list.append(card);
    refresh();
    if (focus) {
      input.focus();
      announce(`${item.type[0].toUpperCase() + item.type.slice(1)} segment added.`);
    }
  }

  document.querySelectorAll("[data-add]").forEach((button) => {
    button.addEventListener("click", () => addSegment({type: button.dataset.add}, true));
  });
  list.addEventListener("click", (event) => {
    const button = event.target.closest("[data-action]");
    if (!button) return;
    const card = button.closest(".segment");
    if (button.dataset.action === "remove") {
      const focusTarget = card.nextElementSibling || card.previousElementSibling;
      if (card.previewUrl) URL.revokeObjectURL(card.previewUrl);
      card.remove();
      refresh();
      (focusTarget?.querySelector(".segment-handle") || document.querySelector("[data-add]")).focus();
      announce("Segment removed.");
    } else {
      move(card, button.dataset.action === "up" ? -1 : 1);
      card.querySelector(".segment-handle").focus();
    }
  });
  list.addEventListener("keydown", (event) => {
    if (!event.target.closest(".segment-handle")) return;
    if (event.key === "ArrowUp" || event.key === "ArrowDown") {
      event.preventDefault();
      move(event.target.closest(".segment"), event.key === "ArrowUp" ? -1 : 1);
      event.target.focus();
    }
  });

  function reorderAtPointer() {
    const others = cards().filter((card) => card !== drag.card);
    const before = others.find((card) => {
      const rect = card.getBoundingClientRect();
      return drag.y < rect.top + rect.height / 2;
    });
    if (drag.card.nextElementSibling !== (before || null)) {
      list.insertBefore(drag.card, before || null);
    }
  }

  function scrollWhileDragging() {
    if (!drag) return;
    if (drag.active) {
      const speed = drag.y < 80 ? -12 : drag.y > window.innerHeight - 80 ? 12 : 0;
      if (speed) {
        window.scrollBy(0, speed);
        reorderAtPointer();
      }
    }
    scrollFrame = requestAnimationFrame(scrollWhileDragging);
  }

  list.addEventListener("pointerdown", (event) => {
    const handle = event.target.closest(".segment-handle");
    if (!handle || event.button !== 0 || fields.disabled || drag) return;
    event.preventDefault();
    handle.focus();
    drag = {card: handle.closest(".segment"), pointerId: event.pointerId, startY: event.clientY, y: event.clientY, active: false};
    // Capture on the stable list so moving a card cannot lose pointer capture.
    list.setPointerCapture(event.pointerId);
    scrollFrame = requestAnimationFrame(scrollWhileDragging);
  });
  list.addEventListener("pointermove", (event) => {
    if (!drag || event.pointerId !== drag.pointerId) return;
    drag.y = event.clientY;
    if (Math.abs(drag.y - drag.startY) > 6) drag.active = true;
    if (drag.active) {
      drag.card.classList.add("dragging");
      reorderAtPointer();
    }
  });
  function endDrag() {
    if (!drag) return;
    const {card, pointerId, active} = drag;
    drag = null;
    cancelAnimationFrame(scrollFrame);
    if (list.hasPointerCapture(pointerId)) list.releasePointerCapture(pointerId);
    card.classList.remove("dragging");
    refresh();
    card.querySelector(".segment-handle").focus({preventScroll: true});
    if (active) announce(`Segment moved to position ${cards().indexOf(card) + 1}.`);
  }
  ["pointerup", "pointercancel", "lostpointercapture"].forEach((name) => list.addEventListener(name, endDrag));

  async function uploadRequest(url, payload) {
    const response = await fetch(url, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)});
    if (response.redirected) throw new Error("Sign in again in another tab, then retry saving here.");
    if (!response.headers.get("content-type")?.includes("application/json")) throw new Error("Could not reach the upload service. Please retry saving.");
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Upload failed. Please retry saving.");
    return result;
  }

  async function uploadMedia(card, file) {
    if (!card.uploaded || card.uploaded.file !== file) {
      card.uploaded = {file, ...await uploadRequest("/admin/uploads/authorize", {
        filename: file.name, size: file.size, media_type: card.dataset.type,
      })};
    }
    const pending = card.uploaded;
    if (!pending.blobDone) {
      const {upload} = await import("/assets/blob-client.js");
      const options = {
        handleUploadUrl: "/api/blob-upload", clientPayload: pending.ticket,
        multipart: true, contentType: pending.content_type,
        onUploadProgress: ({percentage}) => announce(`Uploading ${file.name}: ${Math.round(percentage)}%`),
      };
      try {
        await upload(pending.pathname, file, {...options, access: "public"});
      } catch (failure) {
        if (!/private store|store is private/i.test(failure.message || "")) throw failure;
        await upload(pending.pathname, file, {...options, access: "private"});
      }
      pending.blobDone = true;
    }
    if (!pending.receipt) Object.assign(pending, await uploadRequest("/admin/uploads/complete", {ticket: pending.ticket}));
    return pending;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (fields.disabled) return;
    error.hidden = true;
    const segments = cards().map((card) => ({
      id: card.dataset.id,
      type: card.dataset.type,
      ...(card.dataset.type === "text" ? {text: card.querySelector("textarea").value} : {[`${card.dataset.type}_filename`]: card.dataset.image}),
    }));
    if (!segments.length) {
      showError("Add an image, video, or text segment before saving.");
      return;
    }
    const data = new FormData(form);
    const uploadBytes = Array.from(data.values()).reduce((total, value) => total + (value instanceof File ? value.size : 0), 0);
    const limit = Number(form.dataset.uploadLimit) * 1024 * 1024;
    if (uploadBytes > limit) {
      showError(`The selected files exceed the ${form.dataset.uploadLimit} MiB upload limit. Use smaller files and try again.`);
      return;
    }
    fields.disabled = true;
    announce(`Saving ${contentType}...`);
    try {
      if (form.dataset.directUploads === "true") {
        const items = cards();
        for (let index = 0; index < items.length; index++) {
          const card = items[index];
          const input = card.querySelector("input[type='file']");
          if (!input) continue;
          const file = input.files[0];
          if (file) {
            const uploaded = await uploadMedia(card, file);
            segments[index][`${card.dataset.type}_filename`] = uploaded.reference;
            segments[index].upload_receipt = uploaded.receipt;
          }
          data.delete(input.name);
        }
      }
      data.set("segments", JSON.stringify(segments));
      announce(`Saving ${contentType}...`);
      const response = await fetch(form.action, {method: "POST", body: data, headers: {Accept: "application/json"}});
      if (response.redirected) throw new Error(`Your session has expired. Sign in again in another tab, then save your ${contentType} here.`);
      if (response.status === 413) throw new Error("The selected files are too large to save together. Use smaller files and try again.");
      if (!response.headers.get("content-type")?.includes("application/json")) throw new Error(`Could not save your ${contentType}. Please try again; your segments are still here.`);
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || `Could not save your ${contentType}. Please try again.`);
      window.location.assign(result.redirect);
    } catch (failure) {
      showError(failure.message || `Could not save your ${contentType}. Please try again.`);
      announce("");
      fields.disabled = false;
    }
  });

  JSON.parse(document.getElementById("initial-segments").textContent).forEach((item) => addSegment(item));
  refresh();
})();
