(function () {
  const config = window.PRINT_SERVER || {};
  const allowedExtensions = new Set((config.allowedExtensions || []).map((item) => item.toLowerCase()));
  const maxUploadBytes = Number(config.maxUploadBytes || 0);
  const statusLabels = config.statusLabels || {};
  const adminUsername = config.adminUsername || "admin";

  const form = document.getElementById("uploadForm");
  const input = document.getElementById("fileInput");
  const dropZone = document.getElementById("dropZone");
  const selectedFiles = document.getElementById("selectedFiles");
  const uploadButton = document.getElementById("uploadButton");
  const uploadResults = document.getElementById("uploadResults");
  const jobsBody = document.getElementById("jobsBody");
  const jobCount = document.getElementById("jobCount");
  const queueNotice = document.getElementById("queueNotice");
  const sortAuthForm = document.getElementById("sortAuthForm");
  const sortPassword = document.getElementById("sortPassword");
  const sortAuthButton = document.getElementById("sortAuthButton");
  const sortAuthState = document.getElementById("sortAuthState");
  const adminPanel = document.getElementById("adminPanel");

  if (!form || !input || !dropZone || !selectedFiles || !uploadButton || !uploadResults) {
    return;
  }

  let files = [];
  let uploading = false;
  let sortUnlocked = false;
  let adminAuthHeader = "";
  let draggedRow = null;
  let dragStartOrder = "";

  function updateUploadButton() {
    uploadButton.disabled = uploading || files.length === 0;
    uploadButton.textContent = uploading ? "上传中" : "加入队列";
  }

  function formatSize(value) {
    const units = ["B", "KB", "MB", "GB"];
    let size = Number(value || 0);
    for (const unit of units) {
      if (size < 1024 || unit === units[units.length - 1]) {
        return unit === "B" ? `${Math.round(size)} ${unit}` : `${size.toFixed(1)} ${unit}`;
      }
      size /= 1024;
    }
    return `${value} B`;
  }

  function fileKey(file) {
    return [file.name, file.size, file.lastModified].join(":");
  }

  function fileExtension(name) {
    const index = name.lastIndexOf(".");
    return index >= 0 ? name.slice(index).toLowerCase() : "";
  }

  function validateFile(file) {
    const extension = fileExtension(file.name);
    if (!extension) {
      return { ok: false, text: "缺少扩展名" };
    }
    if (!allowedExtensions.has(extension)) {
      return { ok: false, text: `不支持 ${extension}` };
    }
    if (file.size <= 0) {
      return { ok: false, text: "文件为空" };
    }
    if (maxUploadBytes > 0 && file.size > maxUploadBytes) {
      return { ok: false, text: `超过 ${formatSize(maxUploadBytes)}` };
    }
    return { ok: true, text: "等待上传" };
  }

  function addFiles(fileList) {
    const known = new Set(files.map((item) => item.key));
    for (const file of Array.from(fileList || [])) {
      const key = fileKey(file);
      if (known.has(key)) {
        continue;
      }
      known.add(key);
      const check = validateFile(file);
      files.push({
        key,
        file,
        check,
        status: check.ok ? "待上传" : "待服务器确认",
        detail: check.text,
      });
    }
    input.value = "";
    renderSelectedFiles();
  }

  function removeFile(key) {
    if (uploading) {
      return;
    }
    files = files.filter((item) => item.key !== key);
    renderSelectedFiles();
  }

  function renderSelectedFiles() {
    selectedFiles.replaceChildren();
    if (files.length === 0) {
      const empty = document.createElement("div");
      empty.className = "selected-files-empty";
      empty.textContent = "尚未选择文件";
      selectedFiles.append(empty);
      updateUploadButton();
      return;
    }

    const header = document.createElement("div");
    header.className = "selected-files-header";
    const title = document.createElement("strong");
    title.textContent = "即将上传";
    const count = document.createElement("span");
    count.textContent = `${files.length} 个文件`;
    header.append(title, count);
    selectedFiles.append(header);

    for (const item of files) {
      const row = document.createElement("div");
      const statusClass = item.status === "失败" ? "is-error" : item.status === "已入队" ? "is-done" : "is-ready";
      row.className = `selected-file-row ${statusClass}`;

      const meta = document.createElement("div");
      meta.className = "selected-file-meta";
      const name = document.createElement("strong");
      name.textContent = item.file.name;
      const detail = document.createElement("span");
      detail.textContent = `${formatSize(item.file.size)} · ${item.detail}`;
      meta.append(name, detail);

      const controls = document.createElement("div");
      controls.className = "selected-file-controls";

      const state = document.createElement("span");
      const stateTone = item.status === "失败" ? "error" : item.check.ok ? "ok" : "warn";
      state.className = `file-state ${stateTone}`;
      state.textContent = item.status;

      const removeButton = document.createElement("button");
      removeButton.type = "button";
      removeButton.className = "icon-button remove-file";
      removeButton.disabled = uploading;
      removeButton.setAttribute("aria-label", `移除 ${item.file.name}`);
      removeButton.title = "移除";
      removeButton.textContent = "×";
      removeButton.addEventListener("click", () => removeFile(item.key));

      controls.append(state, removeButton);
      row.append(meta, controls);
      selectedFiles.append(row);
    }
    updateUploadButton();
  }

  function renderBatchResult(data) {
    uploadResults.hidden = false;
    uploadResults.replaceChildren();

    const summary = document.createElement("div");
    summary.className = data.rejected_count ? "notice error" : "notice success";
    summary.textContent = `上传完成：成功 ${data.accepted_count} 个，失败 ${data.rejected_count} 个`;
    uploadResults.append(summary);

    const list = document.createElement("div");
    list.className = "result-list";
    for (const item of data.results || []) {
      const row = document.createElement("div");
      row.className = `result-row ${item.accepted ? "success" : "error"}`;

      const name = document.createElement("strong");
      name.textContent = item.filename;
      const detail = document.createElement("span");
      detail.textContent = item.accepted
        ? `已加入队列 #${item.job.id}`
        : item.error || "上传失败";
      row.append(name, detail);
      list.append(row);
    }
    uploadResults.append(list);
  }

  function applyBatchResultToSelection(data) {
    const results = data.results || [];
    files = files.map((item, index) => {
      const result = results[index];
      if (!result) {
        return item;
      }
      return {
        ...item,
        status: result.accepted ? "已入队" : "失败",
        detail: result.accepted ? `任务 #${result.job.id}` : result.error || "上传失败",
      };
    }).filter((item) => item.status !== "已入队");
    renderSelectedFiles();
  }

  function tableCell(text, className) {
    const cell = document.createElement("td");
    if (className) {
      cell.className = className;
    }
    cell.textContent = text || "";
    return cell;
  }

  function createJobActions(job) {
    const cell = document.createElement("td");
    cell.className = "actions";

    if (job.status === "failed") {
      cell.append(createActionForm(`/admin/jobs/${job.id}/retry`, "重试", "small", "retry"));
    }
    if (job.status !== "printing" && job.status !== "deleted") {
      cell.append(createActionForm(`/admin/jobs/${job.id}/delete`, "删除", "small danger", "delete"));
    }
    return cell;
  }

  function createActionForm(action, label, className, adminAction) {
    const actionForm = document.createElement("form");
    actionForm.method = "post";
    actionForm.action = action;
    actionForm.className = "admin-action-form";
    actionForm.dataset.adminAction = adminAction;
    actionForm.hidden = !sortUnlocked;
    const button = document.createElement("button");
    button.type = "submit";
    button.className = className;
    button.textContent = label;
    actionForm.append(button);
    return actionForm;
  }

  function apiPathForAdminAction(pathname) {
    if (pathname === "/admin/pause") {
      return "/api/admin/pause";
    }
    if (pathname === "/admin/resume") {
      return "/api/admin/resume";
    }
    if (pathname.startsWith("/admin/jobs/")) {
      return `/api${pathname}`;
    }
    return pathname;
  }

  async function handleAdminActionSubmit(event) {
    const actionForm = event.target;
    if (!(actionForm instanceof HTMLFormElement) || !actionForm.classList.contains("admin-action-form")) {
      return;
    }

    event.preventDefault();
    if (!sortUnlocked || !adminAuthHeader) {
      showQueueNotice("请先输入管理员密码完成认证", "error");
      return;
    }

    const actionPath = apiPathForAdminAction(new URL(actionForm.action, window.location.origin).pathname);
    const init = {
      method: "POST",
      credentials: "same-origin",
      headers: { "Authorization": adminAuthHeader },
    };
    if (actionForm.dataset.adminAction === "pause") {
      init.body = new FormData(actionForm);
    }

    try {
      const response = await fetch(actionPath, init);
      if (!response.ok) {
        let detail = "管理操作失败";
        try {
          const payload = await response.json();
          detail = payload.detail || detail;
        } catch (error) {
          detail = response.statusText || detail;
        }
        throw new Error(detail);
      }
      const labels = {
        pause: "服务已暂停",
        resume: "服务已恢复",
        retry: "任务已重新加入队列",
        delete: "任务已删除",
      };
      showQueueNotice(labels[actionForm.dataset.adminAction] || "管理操作已完成", "success");
      await refreshQueue();
    } catch (error) {
      showQueueNotice(error.message || "管理操作失败", "error");
    }
  }

  function showQueueNotice(message, tone) {
    if (!queueNotice) {
      return;
    }
    queueNotice.hidden = false;
    queueNotice.className = `queue-notice ${tone || "success"}`;
    queueNotice.textContent = message;
  }

  function makeBasicAuthHeader(username, password) {
    const bytes = new TextEncoder().encode(`${username}:${password}`);
    let binary = "";
    for (const byte of bytes) {
      binary += String.fromCharCode(byte);
    }
    return `Basic ${btoa(binary)}`;
  }

  function setSortUnlocked(unlocked) {
    sortUnlocked = unlocked;
    if (sortAuthState) {
      sortAuthState.textContent = unlocked ? "管理员已认证，可排序和管理" : "管理员认证后可排序和管理";
      sortAuthState.classList.toggle("is-unlocked", unlocked);
    }
    if (sortPassword) {
      sortPassword.value = "";
      sortPassword.disabled = unlocked;
    }
    if (sortAuthButton) {
      sortAuthButton.textContent = unlocked ? "已认证" : "管理员认证";
      sortAuthButton.disabled = unlocked;
    }
    if (adminPanel) {
      adminPanel.hidden = !unlocked;
    }
    for (const form of document.querySelectorAll(".admin-action-form")) {
      form.hidden = !unlocked;
    }
    setupQueueDragging();
  }

  async function checkSortPassword(event) {
    event.preventDefault();
    if (!sortPassword || !sortPassword.value) {
      showQueueNotice("请输入管理员密码", "error");
      return;
    }

    sortAuthButton.disabled = true;
    sortAuthButton.textContent = "验证中";
    try {
      const response = await fetch("/api/admin/auth/check", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: sortPassword.value }),
      });
      if (!response.ok) {
        throw new Error("管理员密码错误");
      }
      adminAuthHeader = makeBasicAuthHeader(adminUsername, sortPassword.value);
      setSortUnlocked(true);
      showQueueNotice("管理员已认证，可以拖动等待任务并执行管理操作", "success");
    } catch (error) {
      adminAuthHeader = "";
      setSortUnlocked(false);
      showQueueNotice(error.message || "认证失败", "error");
    } finally {
      if (!sortUnlocked && sortAuthButton) {
        sortAuthButton.disabled = false;
        sortAuthButton.textContent = "管理员认证";
      }
    }
  }

  function getWaitingJobIdsFromDom() {
    if (!jobsBody) {
      return [];
    }
    return Array.from(jobsBody.querySelectorAll("tr[data-status='waiting']"))
      .map((row) => Number(row.dataset.jobId))
      .filter((value) => Number.isInteger(value) && value > 0);
  }

  async function saveQueueOrder() {
    const jobIds = getWaitingJobIdsFromDom();
    if (jobIds.length === 0) {
      return;
    }

    try {
      const response = await fetch("/api/admin/jobs/reorder", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Authorization": adminAuthHeader,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ job_ids: jobIds }),
      });
      if (!response.ok) {
        let detail = "保存排序失败";
        try {
          const payload = await response.json();
          detail = payload.detail || detail;
        } catch (error) {
          detail = response.statusText || detail;
        }
        if (response.status === 401) {
          detail = "保存排序需要管理员认证，请先输入管理员密码";
        }
        throw new Error(detail);
      }
      showQueueNotice("打印顺序已保存", "success");
      await refreshQueue();
    } catch (error) {
      showQueueNotice(error.message || "保存排序失败", "error");
      await refreshQueue();
    }
  }

  function isWaitingRow(row) {
    return row instanceof HTMLTableRowElement && row.dataset.status === "waiting";
  }

  function startQueueDrag(row, event) {
    if (!sortUnlocked || !isWaitingRow(row)) {
      event.preventDefault();
      showQueueNotice("请先输入管理员密码解锁排序，且只能拖动等待中的任务", "error");
      return;
    }

    draggedRow = row;
    dragStartOrder = getWaitingJobIdsFromDom().join(",");
    row.classList.add("is-dragging");
    if (event.dataTransfer) {
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.dropEffect = "move";
      event.dataTransfer.setData("text/plain", row.dataset.jobId || "");
    }
  }

  async function finishQueueDrag(row) {
    const changed = dragStartOrder !== getWaitingJobIdsFromDom().join(",");
    row.classList.remove("is-dragging");
    draggedRow = null;
    dragStartOrder = "";
    if (changed) {
      await saveQueueOrder();
    }
  }

  function syncQueueRowDragState(row) {
    const canDrag = sortUnlocked && isWaitingRow(row);
    row.draggable = canDrag;
    row.classList.toggle("is-draggable", canDrag);
    row.classList.toggle("can-drag", canDrag);

    const handle = row.querySelector(".drag-handle");
    if (!handle) {
      return;
    }
    handle.disabled = !canDrag;
    handle.draggable = canDrag;
    handle.title = canDrag ? "按住拖动调整打印顺序" : "管理员认证后可拖动等待任务调整打印顺序";
    handle.setAttribute("aria-disabled", canDrag ? "false" : "true");
  }

  function setupQueueDragging() {
    if (!jobsBody) {
      return;
    }

    jobsBody.classList.toggle("sort-locked", !sortUnlocked);

    if (!jobsBody.dataset.dragBound) {
      jobsBody.dataset.dragBound = "true";
      jobsBody.addEventListener("dragover", (event) => {
        if (!draggedRow || !sortUnlocked) {
          return;
        }
        event.preventDefault();
        if (event.dataTransfer) {
          event.dataTransfer.dropEffect = "move";
        }
        const targetElement = event.target instanceof Element ? event.target : null;
        const target = targetElement ? targetElement.closest("tr[data-status='waiting']") : null;
        if (target && target !== draggedRow) {
          const box = target.getBoundingClientRect();
          const insertAfter = event.clientY > box.top + box.height / 2;
          jobsBody.insertBefore(draggedRow, insertAfter ? target.nextSibling : target);
          return;
        }

        if (!target) {
          const firstLockedRow = Array.from(jobsBody.children).find((row) => row.dataset.status !== "waiting");
          if (firstLockedRow) {
            jobsBody.insertBefore(draggedRow, firstLockedRow);
          } else {
            jobsBody.append(draggedRow);
          }
        }
      });
      jobsBody.addEventListener("drop", (event) => {
        if (draggedRow) {
          event.preventDefault();
        }
      });
    }

    for (const row of jobsBody.querySelectorAll("tr[data-status='waiting']")) {
      syncQueueRowDragState(row);
      if (row.dataset.rowDragBound) {
        continue;
      }
      row.dataset.rowDragBound = "true";
      row.addEventListener("dragstart", (event) => {
        startQueueDrag(row, event);
      });
      row.addEventListener("dragend", async () => {
        await finishQueueDrag(row);
      });

      const handle = row.querySelector(".drag-handle");
      if (handle && !handle.dataset.dragBound) {
        handle.dataset.dragBound = "true";
        handle.addEventListener("dragstart", (event) => {
          event.stopPropagation();
          startQueueDrag(row, event);
        });
        handle.addEventListener("dragend", async (event) => {
          event.stopPropagation();
          await finishQueueDrag(row);
        });
      }
    }
  }

  function renderQueue(jobs) {
    if (!jobsBody || !jobCount) {
      return;
    }
    jobsBody.replaceChildren();
    jobCount.textContent = `${jobs.length} 个任务`;

    if (jobs.length === 0) {
      const row = document.createElement("tr");
      const cell = tableCell("暂无任务", "empty");
      cell.colSpan = 8;
      row.append(cell);
      jobsBody.append(row);
      return;
    }

    for (const job of jobs) {
      const row = document.createElement("tr");
      row.className = `row-${job.status}`;
      row.dataset.jobId = String(job.id);
      row.dataset.status = job.status;
      if (job.status === "waiting" && sortUnlocked) {
        row.classList.add("is-draggable");
        row.draggable = true;
      }

      const dragCell = document.createElement("td");
      dragCell.className = "drag-cell";
      if (job.status === "waiting") {
        const handle = document.createElement("button");
        handle.type = "button";
        handle.className = "drag-handle";
        handle.disabled = !sortUnlocked;
        handle.title = "拖动调整打印顺序";
        handle.setAttribute("aria-label", `拖动任务 #${job.id} 调整打印顺序`);
        handle.textContent = "↕";
        dragCell.append(handle);
      } else {
        const placeholder = document.createElement("span");
        placeholder.className = "drag-placeholder";
        placeholder.textContent = "—";
        dragCell.append(placeholder);
      }
      row.append(dragCell);
      row.append(tableCell(`#${job.id}`));

      const fileCell = document.createElement("td");
      const name = document.createElement("strong");
      name.textContent = job.original_filename;
      const extension = document.createElement("span");
      extension.textContent = job.extension;
      fileCell.append(name, extension);
      row.append(fileCell);

      row.append(tableCell(formatSize(job.size_bytes)));

      const statusCell = document.createElement("td");
      const badge = document.createElement("span");
      badge.className = `badge badge-${job.status}`;
      badge.textContent = statusLabels[job.status] || job.status;
      statusCell.append(badge);
      row.append(statusCell);

      row.append(tableCell(new Date(job.created_at).toLocaleString()));
      row.append(tableCell(job.error_message || "", "error-cell"));
      row.append(createJobActions(job));
      jobsBody.append(row);
    }
    setupQueueDragging();
  }

  async function refreshQueue() {
    const response = await fetch("/api/status", { credentials: "same-origin" });
    if (!response.ok) {
      return;
    }
    const snapshot = await response.json();
    renderQueue(snapshot.jobs || []);
  }

  async function submitUploads(event) {
    event.preventDefault();
    if (uploading) {
      return;
    }
    if (files.length === 0) {
      uploadResults.hidden = false;
      uploadResults.replaceChildren();
      const message = document.createElement("div");
      message.className = "notice error";
      message.textContent = "请选择要上传的文件";
      uploadResults.append(message);
      return;
    }

    uploading = true;
    updateUploadButton();
    files = files.map((item) => ({ ...item, status: "上传中", detail: "正在发送到服务端" }));
    renderSelectedFiles();

    const body = new FormData();
    for (const item of files) {
      body.append("uploads", item.file, item.file.name);
    }

    try {
      const response = await fetch("/api/uploads", {
        method: "POST",
        body,
        credentials: "same-origin",
      });
      if (!response.ok) {
        let detail = "上传失败";
        try {
          const payload = await response.json();
          detail = payload.detail || detail;
        } catch (error) {
          detail = response.statusText || detail;
        }
        throw new Error(detail);
      }

      const data = await response.json();
      applyBatchResultToSelection(data);
      renderBatchResult(data);
      await refreshQueue();
    } catch (error) {
      uploadResults.hidden = false;
      uploadResults.replaceChildren();
      const message = document.createElement("div");
      message.className = "notice error";
      message.textContent = error.message || "上传失败";
      uploadResults.append(message);
      files = files.map((item) => ({ ...item, status: "失败", detail: message.textContent }));
      renderSelectedFiles();
    } finally {
      uploading = false;
      updateUploadButton();
    }
  }

  input.addEventListener("change", () => addFiles(input.files));
  uploadButton.addEventListener("click", submitUploads);
  form.addEventListener("submit", submitUploads);
  if (sortAuthForm) {
    sortAuthForm.addEventListener("submit", checkSortPassword);
  }
  document.addEventListener("submit", handleAdminActionSubmit);

  for (const eventName of ["dragenter", "dragover"]) {
    dropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropZone.classList.add("is-dragging");
    });
  }

  for (const eventName of ["dragleave", "drop"]) {
    dropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropZone.classList.remove("is-dragging");
    });
  }

  dropZone.addEventListener("drop", (event) => {
    addFiles(event.dataTransfer.files);
  });

  document.addEventListener("dragover", (event) => event.preventDefault());
  document.addEventListener("drop", (event) => event.preventDefault());
  renderSelectedFiles();
  setSortUnlocked(false);
  setupQueueDragging();
  window.setInterval(refreshQueue, 12000);
})();
