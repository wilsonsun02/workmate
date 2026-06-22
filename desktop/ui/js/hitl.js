/**
 * HITL（Human-in-the-Loop）对话框管理器
 *
 * 职责：
 * 1. 根据 hitl_wait 事件类型渲染对话框（confirm / input / select）
 * 2. 收集用户输入（选项、文字、附件）
 * 3. 上传附件后将路径拼入 resume_command，调用 resumeFn 恢复执行
 */

function _escHtml(str) {
    return String(str || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

function _buildConfirmArea(ev) {
    var el = document.createElement("div");
    el.className = "hitl-options";
    var selected = null;

    (ev.options || []).forEach(function (opt) {
        var label = document.createElement("label");
        label.className = "hitl-option";

        var radio = document.createElement("input");
        radio.type = "radio";
        radio.name = "hitl-confirm";
        radio.value = opt.value;
        radio.addEventListener("change", function () {
            selected = opt.value;
            el.querySelectorAll(".hitl-option").forEach(function (l) {
                l.classList.remove("selected");
            });
            label.classList.add("selected");
        });

        var content = document.createElement("div");
        content.className = "hitl-option-content";
        content.innerHTML =
            '<div class="hitl-option-label">' + _escHtml(opt.label) + "</div>" +
            (opt.description ? '<div class="hitl-option-desc">' + _escHtml(opt.description) + "</div>" : "");

        label.appendChild(radio);
        label.appendChild(content);
        el.appendChild(label);
    });

    return {
        el: el,
        getResponse: function () {
            if (!selected) return null;
            return { command: { type: "confirm", selected_value: selected }, files: [] };
        },
    };
}

function _renderAttachmentChips(chipList, pendingFiles) {
    chipList.innerHTML = "";
    if (!pendingFiles.length) return;

    pendingFiles.forEach(function (file) {
        var chip = document.createElement("span");
        chip.className = "attachment-chip";

        var nameEl = document.createElement("span");
        nameEl.className = "attachment-chip-name";
        nameEl.textContent = file.name || "file";

        var removeBtn = document.createElement("button");
        removeBtn.type = "button";
        removeBtn.className = "attachment-chip-remove";
        removeBtn.setAttribute("aria-label", "移除附件");
        removeBtn.textContent = "\u00d7";
        removeBtn.addEventListener("click", function (e) {
            e.preventDefault();
            e.stopPropagation();
            var idx = pendingFiles.indexOf(file);
            if (idx >= 0) {
                pendingFiles.splice(idx, 1);
            }
            _renderAttachmentChips(chipList, pendingFiles);
        });

        chip.appendChild(nameEl);
        chip.appendChild(removeBtn);
        chipList.appendChild(chip);
    });
}

function _buildInputArea(ev, apiBase, getUsername) {
    var el = document.createElement("div");
    var pendingFiles = [];

    var textarea = document.createElement("textarea");
    textarea.className = "hitl-textarea";
    textarea.placeholder = ev.placeholder || "请输入...";
    textarea.rows = 5;
    el.appendChild(textarea);

    if (ev.allow_attachments) {
        var attachWrap = document.createElement("div");
        attachWrap.className = "hitl-attachments";

        var chipList = document.createElement("div");
        chipList.className = "hitl-attachment-list";
        attachWrap.appendChild(chipList);

        var uploadLabel = document.createElement("label");
        uploadLabel.className = "hitl-upload-btn";
        uploadLabel.innerHTML = "<span>+ 添加附件</span>";

        var fileInput = document.createElement("input");
        fileInput.type = "file";
        fileInput.multiple = true;
        fileInput.style.display = "none";
        fileInput.addEventListener("change", function () {
            Array.from(fileInput.files).forEach(function (f) {
                pendingFiles.push(f);
            });
            _renderAttachmentChips(chipList, pendingFiles);
            fileInput.value = "";
        });

        uploadLabel.appendChild(fileInput);
        attachWrap.appendChild(uploadLabel);
        el.appendChild(attachWrap);
    }

    setTimeout(function () { textarea.focus(); }, 50);

    return {
        el: el,
        getResponse: function () {
            return {
                command: { type: "input", text_input: textarea.value.trim() },
                files: pendingFiles,
            };
        },
    };
}

function _buildSelectArea(ev, apiBase, getUsername) {
    var el = document.createElement("div");
    el.className = "hitl-options";
    var selected = new Set();
    var isMulti = !!ev.multi_select;
    var pendingFiles = [];

    (ev.options || []).forEach(function (opt) {
        var label = document.createElement("label");
        label.className = "hitl-option";

        var input = document.createElement("input");
        input.type = isMulti ? "checkbox" : "radio";
        input.name = "hitl-select";
        input.value = opt.value;
        input.addEventListener("change", function () {
            if (isMulti) {
                if (input.checked) selected.add(opt.value);
                else selected.delete(opt.value);
                label.classList.toggle("selected", input.checked);
            } else {
                selected.clear();
                selected.add(opt.value);
                el.querySelectorAll(".hitl-option").forEach(function (l) {
                    l.classList.remove("selected");
                });
                label.classList.add("selected");
            }
        });

        var content = document.createElement("div");
        content.className = "hitl-option-content";
        content.innerHTML =
            '<div class="hitl-option-label">' + _escHtml(opt.label) + "</div>" +
            (opt.description ? '<div class="hitl-option-desc">' + _escHtml(opt.description) + "</div>" : "");

        label.appendChild(input);
        label.appendChild(content);
        el.appendChild(label);
    });

    if (ev.allow_attachments) {
        var attachWrap = document.createElement("div");
        attachWrap.className = "hitl-attachments";

        var chipList = document.createElement("div");
        chipList.className = "hitl-attachment-list";
        attachWrap.appendChild(chipList);

        var uploadLabel = document.createElement("label");
        uploadLabel.className = "hitl-upload-btn";
        uploadLabel.innerHTML = "<span>+ 添加附件</span>";

        var fileInput = document.createElement("input");
        fileInput.type = "file";
        fileInput.multiple = true;
        fileInput.style.display = "none";
        fileInput.addEventListener("change", function () {
            Array.from(fileInput.files).forEach(function (f) {
                pendingFiles.push(f);
            });
            _renderAttachmentChips(chipList, pendingFiles);
            fileInput.value = "";
        });

        uploadLabel.appendChild(fileInput);
        attachWrap.appendChild(uploadLabel);
        el.appendChild(attachWrap);
    }

    return {
        el: el,
        getResponse: function () {
            if (selected.size === 0) return null;
            var vals = Array.from(selected);
            return {
                command: { type: "select", selected_values: vals },
                files: pendingFiles,
            };
        },
    };
}

async function _uploadFiles(files, apiBase, username) {
    if (!files || files.length === 0) return [];
    var formData = new FormData();
    formData.append("username", username || "");
    for (var i = 0; i < files.length; i++) {
        formData.append("files", files[i]);
    }
    try {
        var res = await fetch(apiBase + "/api/desktop/upload", {
            method: "POST",
            body: formData,
        });
        if (res.ok) {
            var data = await res.json();
            if (data && data.ok && Array.isArray(data.paths)) {
                return data.paths;
            }
        }
    } catch (_e) {
        /* 上传失败不阻断整体流程 */
    }
    return [];
}

/**
 * 创建 HITL 管理器实例
 *
 * @param {object} opts
 * @param {string} opts.apiBase - API 基础地址
 * @param {Function} opts.getUsername - 返回当前用户名的函数
 * @param {Function} opts.resumeFn - 恢复执行的回调，签名：(conv, command, attachmentPaths) => void
 * @returns {{ show: Function, close: Function }}
 */
export function createHITLManager(opts) {
    var apiBase = opts.apiBase || "";
    var getUsername = opts.getUsername || function () { return ""; };
    var resumeFn = opts.resumeFn;
    var currentOverlay = null;

    function close() {
        if (currentOverlay && currentOverlay.parentNode) {
            currentOverlay.parentNode.removeChild(currentOverlay);
        }
        currentOverlay = null;
    }

    function show(ev, conv, onResumed) {
        close();

        var overlay = document.createElement("div");
        overlay.className = "hitl-overlay";
        currentOverlay = overlay;

        var card = document.createElement("div");
        card.className = "hitl-card";

        var title = document.createElement("h3");
        title.className = "hitl-title";
        title.textContent = "需要您的确认";
        card.appendChild(title);

        var msg = document.createElement("p");
        msg.className = "hitl-message";
        msg.textContent = ev.message || "";
        card.appendChild(msg);

        var interactionEl = null;
        var getResponse = null;

        if (ev.hitl_type === "confirm") {
            var r = _buildConfirmArea(ev);
            interactionEl = r.el;
            getResponse = r.getResponse;
        } else if (ev.hitl_type === "input") {
            var r = _buildInputArea(ev, apiBase, getUsername);
            interactionEl = r.el;
            getResponse = r.getResponse;
        } else if (ev.hitl_type === "select") {
            var r = _buildSelectArea(ev, apiBase, getUsername);
            interactionEl = r.el;
            getResponse = r.getResponse;
        }

        if (interactionEl) card.appendChild(interactionEl);

        var actions = document.createElement("div");
        actions.className = "hitl-actions";

        var cancelBtn = document.createElement("button");
        cancelBtn.className = "btn-confirm-secondary";
        cancelBtn.textContent = "取消";
        cancelBtn.addEventListener("click", function () {
            close();
            resumeFn(conv, { type: "confirm", selected_value: "reject" }, []);
        });

        var submitBtn = document.createElement("button");
        submitBtn.className = "btn-submit";
        submitBtn.textContent = "确认";
        submitBtn.addEventListener("click", async function () {
            if (!getResponse) return;
            var resp = getResponse();
            if (!resp) {
                var hint = card.querySelector(".hitl-hint");
                if (!hint) {
                    hint = document.createElement("p");
                    hint.className = "hitl-hint";
                    hint.textContent = "请先做出选择后再确认";
                    actions.insertBefore(hint, cancelBtn);
                }
                hint.style.display = "block";
                return;
            }
            submitBtn.disabled = true;
            close();
            var attachPaths = await _uploadFiles(resp.files || [], apiBase, getUsername());
            resumeFn(conv, resp.command, attachPaths);
            if (onResumed) onResumed();
        });

        actions.appendChild(cancelBtn);
        actions.appendChild(submitBtn);
        card.appendChild(actions);

        overlay.appendChild(card);
        document.body.appendChild(overlay);
    }

    return { show: show, close: close };
}
