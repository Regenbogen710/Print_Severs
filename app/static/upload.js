(function () {
  const config = window.PRINT_SERVER || {};
  const allowedExtensions = new Set((config.allowedExtensions || []).map((item) => item.toLowerCase()));
  const maxUploadBytes = Number(config.maxUploadBytes || 0);
  const statusLabels = config.statusLabels || {};

  const form = document.getElementById("uploadForm");
  const input = document.getElementById("fileInput");
  const dropZone = document.getElementById("dropZone");
  const selectedFiles = document.getElementById("selectedFiles");
  const uploadButton = document.getElementById("uploadButton");
  const uploadResults = document.getElementById("uploadResults");
  const jobsBody = document.getElementById("jobsBody");
  const jobCount = document.getElementById("jobCount");

  if (!form || !input || !dropZone || !selectedFiles || !uploadButton || !uploadResults) {
    return;
  }

  let files = [];
  let uploading = false;

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

  function renderSelectedFiles() {
    selectedFiles.replaceChildren();
    if (files.length === 0) {
      selectedFiles.textContent = "尚未选择文件";
      return;
    }

    for (const item of files) {
      const row = document.createElement("div");
      row.className = "selected-file-row";

      const meta = document.createElement("div");
      const name = document.createElement("strong");
      name.textContent = item.file.name;
      const detail = document.createElement("span");
      detail.textContent = `${formatSize(item.file.size)} · ${item.detail}`;
      meta.append(name, detail);

      const state = document.createElement("span");
      state.className = `file-state ${item.check.ok ? "ok" : "warn"}`;
      state.textContent = item.status;

      row.append(meta, state);
      selectedFiles.append(row);
    }
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
    });
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
      cell.append(createActionForm(`/admin/jobs/${job.id}/retry`, "重试", "small"));
    }
    if (job.status !== "printing" && job.status !== "deleted") {
      cell.append(createActionForm(`/admin/jobs/${job.id}/delete`, "删除", "small danger"));
    }
    return cell;
  }

  function createActionForm(action, label, className) {
    const actionForm = document.createElement("form");
    actionForm.method = "post";
    actionForm.action = action;
    const button = document.createElement("button");
    button.type = "submit";
    button.className = className;
    button.textContent = label;
    actionForm.append(button);
    return actionForm;
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
      cell.colSpan = 7;
      row.append(cell);
      jobsBody.append(row);
      return;
    }

    for (const job of jobs) {
      const row = document.createElement("tr");
      row.className = `row-${job.status}`;
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
    uploadButton.disabled = true;
    uploadButton.textContent = "上传中";
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
      uploadButton.disabled = false;
      uploadButton.textContent = "加入队列";
    }
  }

  input.addEventListener("change", () => addFiles(input.files));
  form.addEventListener("submit", submitUploads);

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
  window.setInterval(refreshQueue, 12000);
})();
