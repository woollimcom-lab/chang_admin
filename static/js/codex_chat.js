(function () {
    const STORAGE_KEY = "codex-max-conversation-task-id";
    const MODE_STORAGE_KEY = "codex-max-composer-mode";
    const PROJECT_STORAGE_KEY = "codex-max-project-id";
    const PROJECT_DRAWER_STORAGE_KEY = "codex-max-project-drawer-open";
    const PROJECT_SUMMARY_STORAGE_KEY = "codex-max-project-summary-open";
    const DRAFT_STORAGE_KEY = "codex-max-draft";
    const PANEL_STORAGE_KEY = "codex-max-panel-state";
    const SECTION_STORAGE_KEY = "codex-max-section-state";
    const CHAT_TIMELINE_STORAGE_KEY = "codex-max-chat-timeline";
    const ACTIVE_POLL_MS = 7000;
    const IDLE_POLL_MS = 15000;
    const BANNER_TICK_MS = 2400;
    const MOBILE_QUEUE_BREAKPOINT = 840;
    const rootEl = document.getElementById("codexChatApp");
    let currentView = {};
    let pendingRequest = false;
    let selectedComposerMode = "";
    let pollTimer = 0;
    let stateEventSource = null;
    let stateEventKey = "";
    let bannerTickerTimer = 0;
    let toastTimer = 0;
    let lastCompletionTaskId = "";
    let previousTaskSnapshot = { id: "", status: "" };
    let queuePanelOpen = false;
    let projectDrawerOpen = false;
    let projectCreateOpen = false;
    let projectSummaryOpen = false;
    let selectedProjectId = "";
    let projectFilterText = "";
    let projectFilterStage = "ALL";
    let progressMonitor = { taskId: "", signature: "", stagnantPolls: 0 };
    let lastStalledTaskId = "";
    let pendingCommandConfirmation = null;

    function canAutoRunPrimaryAction(viewModel) {
        const action = text(viewModel?.primary_action?.action);
        return Boolean(action) && !Boolean(viewModel?.primary_action?.disabled);
    }

    function byId(id) {
        return rootEl?.querySelector(`#${id}`) || document.getElementById(id);
    }

    function setProjectDrawerOpen(nextOpen) {
        const drawerEl = byId("projectDrawer");
        const overlayEl = byId("projectDrawerOverlay");
        const toggleButtonEl = byId("projectDrawerToggleButton");
        projectDrawerOpen = Boolean(nextOpen);
        try {
            window.localStorage.setItem(PROJECT_DRAWER_STORAGE_KEY, projectDrawerOpen ? "1" : "0");
        } catch (_error) {}
        if (drawerEl) {
            drawerEl.classList.toggle("is-open", projectDrawerOpen);
            drawerEl.setAttribute("aria-hidden", projectDrawerOpen ? "false" : "true");
        }
        if (overlayEl) {
            overlayEl.hidden = !projectDrawerOpen;
            overlayEl.classList.toggle("visible", projectDrawerOpen);
        }
        if (toggleButtonEl) {
            toggleButtonEl.setAttribute("aria-expanded", projectDrawerOpen ? "true" : "false");
        }
    }

    function setProjectCreateOpen(nextOpen) {
        const formEl = byId("projectFormSection");
        const toggleButtonEl = byId("projectCreateToggleButton");
        projectCreateOpen = Boolean(nextOpen);
        if (formEl) {
            formEl.hidden = !projectCreateOpen;
        }
        if (toggleButtonEl) {
            toggleButtonEl.textContent = projectCreateOpen ? "생성 닫기" : "새 프로젝트";
            toggleButtonEl.setAttribute("aria-expanded", projectCreateOpen ? "true" : "false");
        }
    }

    function setProjectSummaryOpen(nextOpen) {
        const detailsEl = byId("projectSummaryDetails");
        const toggleButtonEl = byId("projectSummaryToggleButton");
        projectSummaryOpen = Boolean(nextOpen);
        try {
            window.localStorage.setItem(PROJECT_SUMMARY_STORAGE_KEY, projectSummaryOpen ? "1" : "0");
        } catch (_error) {}
        if (detailsEl) {
            detailsEl.hidden = !projectSummaryOpen;
        }
        if (toggleButtonEl) {
            toggleButtonEl.textContent = projectSummaryOpen ? "세부 닫기" : "세부 보기";
            toggleButtonEl.setAttribute("aria-expanded", projectSummaryOpen ? "true" : "false");
        }
    }

    function detectWorkspaceSource() {
        const host = text(window.location.hostname).toLowerCase();
        if (host === "127.0.0.1" || host === "localhost") {
            return { tone: "local", label: "로컬 본체" };
        }
        if (/trycloudflare\.com$/.test(host)) {
            return { tone: "tunnel", label: "터널 연결" };
        }
        return { tone: "server", label: "서버 진입" };
    }

    function setQueuePanelOpen(nextOpen) {
        const shellEl = byId("queuePanelShell");
        const overlayEl = byId("queuePanelOverlay");
        const toggleButtonEl = byId("queuePanelToggleButton");
        const hasQueueContent = !isThinBridgeMode(currentView) && Boolean((currentView?.recent_tasks || []).length || currentView?.current_task);
        queuePanelOpen = hasQueueContent ? Boolean(nextOpen) : false;
        if (shellEl) {
            shellEl.classList.toggle("is-open", queuePanelOpen);
        }
        if (overlayEl) {
            overlayEl.hidden = !queuePanelOpen;
            overlayEl.classList.toggle("visible", queuePanelOpen);
        }
        if (toggleButtonEl) {
            toggleButtonEl.hidden = !hasQueueContent;
            toggleButtonEl.textContent = queuePanelOpen ? "작업 목록 내리기" : "작업 목록 올리기";
            toggleButtonEl.setAttribute("aria-expanded", queuePanelOpen ? "true" : "false");
        }
    }

    function parseJsonScript(id) {
        const el = byId(id);
        if (!el || !el.textContent) return null;
        try {
            return JSON.parse(el.textContent);
        } catch (_error) {
            return null;
        }
    }

    function text(value, fallback = "") {
        const rendered = String(value ?? "").trim();
        return rendered || fallback;
    }

    function hasPendingConfirmation() {
        return Boolean(pendingCommandConfirmation && text(pendingCommandConfirmation.message));
    }

    function pendingConfirmationMessage() {
        return text(pendingCommandConfirmation?.message);
    }

    function interpretPendingIntent(message) {
        const normalized = text(message).replace(/\s+/g, " ").trim();
        if (!normalized) {
            return {
                lead: "이렇게 이해했습니다.",
                summary: "새 작업을 시작하려는 요청입니다.",
                plan: "진행 방식: 범위를 확인한 뒤 필요한 작업만 수행하고 결과를 보고합니다.",
                next: "맞으면 [맞아요, 진행], 다르면 [다시 설명]을 눌러 주세요.",
            };
        }
        let action = "새 작업을 시작하려는 요청";
        if (/(검증|확인|체크|점검|테스트)/.test(normalized)) {
            action = "현재 흐름이 의도대로 동작하는지 확인하는 요청";
        } else if (/(요지|이해|판독|앵무새|그대로|승인).*(진행|실행|처리|작업)|(?:진행|실행|처리|작업).*(요지|이해|판독|승인)/.test(normalized)) {
            action = "지시를 해석한 뒤 승인 후 실행하는 흐름으로 바꾸려는 요청";
        } else if (/(수정|고쳐|해결|복구|디버그|막힘)/.test(normalized)) {
            action = "문제를 고치거나 막힌 지점을 푸는 요청";
        } else if (/(확인|체크|점검|검토|판단|검증|테스트)/.test(normalized)) {
            action = "현재 상태를 확인하고 판단하는 요청";
        } else if (/(계획|플랜|순서|단계|로드맵)/.test(normalized)) {
            action = "실행 계획부터 정리하는 요청";
        } else if (/(요약|정리|압축)/.test(normalized)) {
            action = "핵심만 짧게 정리하는 요청";
        } else if (/(설명|뜻|이유|왜|알려줘|말해줘)/.test(normalized)) {
            action = "의미와 이유를 설명받는 요청";
        } else if (/(구현|만들|추가|연결|붙여|적용)/.test(normalized)) {
            action = "기능을 만들거나 연결하는 요청";
        }
        const scopes = [];
        if (/codex-chat/i.test(normalized)) scopes.push("codex-chat");
        if (/모바일|화면|UI|UX|채팅|버블/.test(normalized)) scopes.push("모바일 채팅 화면");
        if (/요지|이해|판독|승인|계획/.test(normalized)) scopes.push("지시 이해/승인 흐름");
        if (/결과|요약|반영/.test(normalized)) scopes.push("결과 표시");
        if (/서버|API|SSE|WebSocket|실시간/.test(normalized)) scopes.push("서버/실시간 반영");
        if (/문맥|프롬프트|이전 대화/.test(normalized)) scopes.push("대화 문맥");
        if (/프로젝트/.test(normalized)) scopes.push("프로젝트");
        if (/업로드|배포/.test(normalized)) scopes.push("반영 흐름");
        if (/로그|메시지|문구/.test(normalized)) scopes.push("화면 문구");
        if (/검증|테스트/.test(normalized)) scopes.push("검증");
        const uniqueScopes = [...new Set(scopes)].slice(0, 3);
        const scopeText = uniqueScopes.length ? `${uniqueScopes.join(" / ")}에 대해 ` : "";
        const constraints = [];
        if (/(그대로|유지|깨지지|바꾸지|추가.*금지|금지)/.test(normalized)) constraints.push("기존 흐름은 최대한 유지");
        if (/(최소|간단|단순|얇은|브리지)/.test(normalized)) constraints.push("최소 변경 우선");
        if (/(승인|확인 후|먼저.*보고|계획)/.test(normalized)) constraints.push("실행 전 확인 필요");
        const constraintText = constraints.length ? ` 조건: ${[...new Set(constraints)].join(", ")}.` : "";
        return {
            lead: "이렇게 이해했습니다.",
            summary: `요지: ${scopeText}${action}입니다.${constraintText}`,
            plan: "진행 방식: 현재 상태를 확인하고 필요한 작업만 수행한 뒤 결과를 보고합니다.",
            next: "승인 안내: 맞으면 [맞아요, 진행], 다르면 [다시 설명]을 눌러 주세요.",
        };
    }

    function compactTimestamp(value) {
        const rendered = text(value);
        if (!rendered) return "기록 없음";
        const parts = rendered.split(" ");
        if (parts.length < 2) return rendered;
        const [datePart, timePart] = parts;
        const today = new Date();
        const todayKey = [
            today.getFullYear(),
            String(today.getMonth() + 1).padStart(2, "0"),
            String(today.getDate()).padStart(2, "0"),
        ].join("-");
        return datePart === todayKey ? timePart : `${datePart} ${timePart}`;
    }

    function compactSummaryText(value, maxLength = 96) {
        const rendered = text(value);
        if (!rendered) return "아직 결과 요약이 없습니다.";
        const normalized = rendered.replace(/\s+/g, " ").trim();
        if (normalized.length <= maxLength) return normalized;
        return `${normalized.slice(0, maxLength).trim()}…`;
    }

    function compactChatText(value, maxLength = 520) {
        const rendered = text(value).replace(/\s+/g, " ").trim();
        if (!rendered) return "";
        if (rendered.length <= maxLength) return rendered;
        return `${rendered.slice(0, maxLength).trim()}…`;
    }

    function bridgeRunStateLabel(viewModel) {
        const key = text(viewModel?.run_state).toUpperCase();
        if (key === "RUNNING") return "실행중";
        if (key === "NEEDS_USER_INPUT") return "질문 필요";
        if (key === "DONE") return "완료";
        if (key === "FAILED") return "실패";
        return "대기";
    }

    function bridgeStatusCopy(viewModel, task) {
        const progress = Number(viewModel?.progress_percent ?? task?.progress_percent ?? 0);
        const stateLabel = bridgeRunStateLabel(viewModel);
        return {
            headline: text(viewModel?.status_message, stateLabel),
            preExecution: text(viewModel?.pre_execution_check || viewModel?.understanding),
            understanding: text(viewModel?.understanding),
            waitHint: text(viewModel?.wait_hint),
            result: text(viewModel?.result_message || viewModel?.summary || task?.summary),
            progressText: progress > 0 ? `${Math.max(0, Math.min(100, progress))}%` : "",
        };
    }

    function readChatTimeline() {
        try {
            const rows = JSON.parse(window.localStorage.getItem(CHAT_TIMELINE_STORAGE_KEY) || "[]");
            return Array.isArray(rows) ? rows.filter((row) => text(row?.body)).slice(-90) : [];
        } catch (_error) {
            return [];
        }
    }

    function writeChatTimeline(rows) {
        try {
            window.localStorage.setItem(CHAT_TIMELINE_STORAGE_KEY, JSON.stringify((rows || []).slice(-90)));
        } catch (_error) {}
    }

    function mergeChatTimeline(nextRows) {
        const existing = readChatTimeline();
        const nextKeys = new Set((nextRows || []).map((row) => text(row.key)).filter(Boolean));
        const kept = existing.filter((row) => !nextKeys.has(text(row.key)));
        const merged = [...kept, ...(nextRows || [])].filter((row) => text(row.body)).slice(-90);
        writeChatTimeline(merged);
        return merged;
    }

    function buildThinBridgeTimelineRows() {
        if (hasPendingConfirmation()) {
            const interpretation = interpretPendingIntent(pendingConfirmationMessage());
            return [
                {
                    role: "user",
                    label: "나",
                    created_at: "",
                    body: pendingConfirmationMessage(),
                },
                {
                    role: "system",
                    label: "이해 확인",
                    created_at: "",
                    body: [interpretation.lead, interpretation.summary, interpretation.plan, interpretation.next].filter(Boolean).join("\n"),
                    actions: [
                        { kind: "run", label: "맞아요, 진행", tone: "primary" },
                        { kind: "edit", label: "다시 설명", tone: "outline" },
                    ],
                },
            ];
        }

        const task = currentView.current_task || null;
        const bridgeCopy = bridgeStatusCopy(currentView, task);
        const taskKey = text(currentView.conversation_task_id || task?.id || currentView.updated_at || currentView.command, "latest");
        const updatedAt = text(currentView.updated_at || task?.updated_at);
        const command = compactChatText(currentView.command || task?.title);
        const statusBody = compactChatText([bridgeCopy.preExecution, bridgeCopy.headline, bridgeCopy.waitHint].filter(Boolean).join("\n"));
        const resultBody = compactChatText(bridgeCopy.result || currentView.summary || task?.summary);
        const rows = [];

        if (command) {
            rows.push({
                key: `${taskKey}:command`,
                role: "user",
                label: "나",
                created_at: updatedAt ? compactTimestamp(updatedAt) : "",
                body: command,
            });
        }
        if (statusBody) {
            rows.push({
                key: `${taskKey}:status`,
                role: "system",
                label: bridgeRunStateLabel(currentView),
                created_at: updatedAt ? compactTimestamp(updatedAt) : "",
                body: statusBody,
            });
        }
        if (resultBody && text(currentView.run_state).toUpperCase() !== "IDLE") {
            rows.push({
                key: `${taskKey}:result`,
                role: "result",
                label: "결과",
                created_at: updatedAt ? compactTimestamp(updatedAt) : "",
                body: resultBody,
            });
        }
        return rows.length ? mergeChatTimeline(rows) : readChatTimeline();
    }

    function isThinBridgeMode(viewModel = currentView) {
        return text(viewModel?.bridge_mode) === "thin-bridge" || text(viewModel?.view_kind) === "codex-max-minimal";
    }

    function projectConversationCopy(project, task) {
        const selectedProject = project || null;
        if (!selectedProject || !text(selectedProject.id)) {
            return null;
        }
        const title = text(selectedProject.title, "선택된 프로젝트");
        const stageLabel = text(selectedProject.stage_label, "기획");
        const statusHint = text(selectedProject.status_hint);
        const activeTitle = text(selectedProject.active_plan_title);
        const workspaceBrief = text(selectedProject.workspace_brief);
        const workspaceStateLine = text(selectedProject.workspace_state_line, statusHint);
        const remainingCount = Number(selectedProject.plan_remaining_count || 0);
        const doneCount = Number(selectedProject.plan_done_count || 0);
        if (!task) {
            if (!selectedProject.approved) {
                return {
                    composerHint: "계획만 남기면 됩니다.",
                    composerHelper: "승인만 하면 됩니다.",
                    sendButtonLabel: "계획 남기기",
                    sendAndRunLabel: "계획 만들기",
                    placeholder: `${title} 프로젝트에서 먼저 정리할 목표나 기능을 한 줄로 입력하세요.`,
                    logSubtitle: "계획이 여기 이어집니다.",
                    introMessage: `${title} · ${workspaceBrief || workspaceStateLine || stageLabel}`,
                };
            }
            return {
                composerHint: "다음 지시만 남기면 됩니다.",
                composerHelper: "다음 지시만 남기면 됩니다.",
                sendButtonLabel: "지시 보내기",
                sendAndRunLabel: "보내고 바로 이어가기",
                placeholder: `${title} 프로젝트에서 이어서 처리할 지시를 한 줄로 입력하세요.`,
                logSubtitle: "실행이 여기 이어집니다.",
                introMessage: `${title} · ${workspaceBrief || workspaceStateLine || "자동 실행 준비"}`,
            };
        }
        return {
            composerHint: "후속 지시만 남기면 됩니다.",
            composerHelper: "후속 지시만 남기면 됩니다.",
            sendButtonLabel: "후속 지시 보내기",
            sendAndRunLabel: "보내고 바로 이어가기",
            placeholder: `${title} 프로젝트의 현재 작업에 남길 후속 지시를 한 줄로 입력하세요.`,
            logSubtitle: "흐름이 여기 이어집니다.",
            introMessage: `${title} · ${workspaceBrief || activeTitle || workspaceStateLine || "후속 지시 대기"}`,
        };
    }

    function projectStageOrder(status) {
        const key = text(status).toUpperCase();
        if (key === "PLANNING") return 0;
        if (key === "APPROVAL") return 1;
        if (key === "ACTIVE") return 2;
        return 3;
    }

    function projectStageTrackRows(status) {
        const currentIndex = projectStageOrder(status);
        return [
            { label: "기획", copy: "요구/세부 계획", state: currentIndex > 0 ? "done" : currentIndex === 0 ? "active" : "idle" },
            { label: "승인", copy: "계획 확인", state: currentIndex > 1 ? "done" : currentIndex === 1 ? "active" : "idle" },
            { label: "자동", copy: "계획대로 실행", state: currentIndex > 2 ? "done" : currentIndex === 2 ? "active" : "idle" },
            { label: "마감", copy: "완료/보류", state: currentIndex === 3 ? "active" : "idle" },
        ];
    }

    function renderProjectStageTrack(trackEl, status) {
        if (!trackEl) return;
        const rows = projectStageTrackRows(status);
        trackEl.innerHTML = rows.map((row) => `
            <div class="project-stage-chip" data-state="${escapeHtml(row.state)}">
                <div class="project-stage-chip-label">${escapeHtml(row.label)}</div>
                <div class="project-stage-chip-copy">${escapeHtml(row.copy)}</div>
            </div>
        `).join("");
    }

    function projectExecutionPulse(project) {
        const status = text(project?.status).toUpperCase();
        const progress = Math.max(0, Math.min(100, Number(project?.progress_percent || 0)));
        const planItems = Array.isArray(project?.plan_items) ? project.plan_items : [];
        const remainingCount = Math.max(0, Number(project?.plan_remaining_count || 0));
        const activeItem = planItems.find((item) => /IN_PROGRESS|ACTIVE|RUNNING/i.test(text(item?.status)));
        const waitingApproval = !Boolean(project?.approved);
        const workspaceBrief = text(project?.workspace_brief);
        if (status === "DONE") {
            return "완료된 프로젝트입니다. 결과만 확인하면 됩니다.";
        }
        if (status === "HOLD") {
            return "보류 상태입니다. 다시 시작할 계획만 정리하면 됩니다.";
        }
        if (waitingApproval) {
            return "승인만 하면 자동 실행으로 넘어갑니다.";
        }
        if (workspaceBrief) {
            return workspaceBrief;
        }
        if (activeItem) {
            return `'${text(activeItem.title, "자동 실행")}' 진행 중 · ${progress}%`;
        }
        return `자동 실행 준비 중 · ${remainingCount > 0 ? `남은 단계 ${remainingCount}개` : "다음 단계 대기"}`;
    }

    function projectLogLead(project, task) {
        if (!project || !text(project.id)) {
            return "";
        }
        const workspaceLogLine = text(project.workspace_log_line);
        const workspaceBrief = text(project.workspace_brief);
        const statusHint = text(project.workspace_state_line || project.status_hint);
        if (workspaceLogLine) {
            return workspaceLogLine;
        }
        if (!project.approved) {
            return "승인만 하면 자동 실행으로 넘어갑니다.";
        }
        if (task) {
            return workspaceBrief || statusHint || "프로젝트 실행 중입니다.";
        }
        return workspaceBrief || statusHint || "프로젝트 흐름을 이어갑니다.";
    }

    function projectStageTone(status) {
        const key = text(status).toUpperCase();
        if (key === "ACTIVE") return "active";
        if (key === "DONE") return "done";
        if (key === "HOLD") return "hold";
        if (key === "APPROVAL") return "approval";
        return "planning";
    }

    function escapeHtml(value) {
        return text(value)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function syncUrlState({ taskId = "", composerMode = "", projectId = "" } = {}) {
        try {
            const url = new URL(window.location.href);
            if (taskId) {
                url.searchParams.set("conversation_task_id", taskId);
            } else {
                url.searchParams.delete("conversation_task_id");
            }
            if (composerMode) {
                url.searchParams.set("composer_mode", composerMode);
            } else {
                url.searchParams.delete("composer_mode");
            }
            if (projectId) {
                url.searchParams.set("project_id", projectId);
            } else {
                url.searchParams.delete("project_id");
            }
            window.history.replaceState({}, "", url.toString());
        } catch (_error) {}
    }

    function saveConversationTaskId(taskId) {
        const id = text(taskId);
        if (id) {
            window.localStorage.setItem(STORAGE_KEY, id);
        } else {
            window.localStorage.removeItem(STORAGE_KEY);
        }
        syncUrlState({ taskId: id, composerMode: selectedComposerMode, projectId: selectedProjectId });
    }

    function loadConversationTaskIdFromUrl() {
        try {
            return text(new URL(window.location.href).searchParams.get("conversation_task_id"));
        } catch (_error) {
            return "";
        }
    }

    function loadSavedConversationTaskId() {
        return loadConversationTaskIdFromUrl() || text(window.localStorage.getItem(STORAGE_KEY));
    }

    function saveComposerMode(mode) {
        const cleanMode = text(mode);
        if (cleanMode) {
            window.localStorage.setItem(MODE_STORAGE_KEY, cleanMode);
        } else {
            window.localStorage.removeItem(MODE_STORAGE_KEY);
        }
        syncUrlState({ taskId: text(currentView.conversation_task_id), composerMode: cleanMode, projectId: selectedProjectId });
    }

    function saveSelectedProjectId(projectId) {
        const id = text(projectId);
        selectedProjectId = id;
        if (id) {
            window.localStorage.setItem(PROJECT_STORAGE_KEY, id);
        } else {
            window.localStorage.removeItem(PROJECT_STORAGE_KEY);
        }
        syncUrlState({ taskId: text(currentView.conversation_task_id), composerMode: selectedComposerMode, projectId: id });
    }

    function loadProjectIdFromUrl() {
        try {
            return text(new URL(window.location.href).searchParams.get("project_id"));
        } catch (_error) {
            return "";
        }
    }

    function loadSavedProjectId() {
        return loadProjectIdFromUrl() || text(window.localStorage.getItem(PROJECT_STORAGE_KEY));
    }

    function loadComposerModeFromUrl() {
        try {
            return text(new URL(window.location.href).searchParams.get("composer_mode"));
        } catch (_error) {
            return "";
        }
    }

    function loadSavedComposerMode() {
        return loadComposerModeFromUrl() || text(window.localStorage.getItem(MODE_STORAGE_KEY));
    }

    function currentDraftKey(taskId = "", mode = "") {
        const cleanTaskId = text(taskId, text(currentView.conversation_task_id));
        const cleanMode = text(mode, text(selectedComposerMode, text(currentView.composer?.selected_mode || currentView.composer?.mode, "new-task")));
        if (cleanMode === "followup" && cleanTaskId) {
            return `${DRAFT_STORAGE_KEY}:followup:${cleanTaskId}`;
        }
        return `${DRAFT_STORAGE_KEY}:new-task`;
    }

    function readDraft(taskId = "", mode = "") {
        try {
            return text(window.localStorage.getItem(currentDraftKey(taskId, mode)));
        } catch (_error) {
            return "";
        }
    }

    function writeDraft(value, taskId = "", mode = "") {
        try {
            const key = currentDraftKey(taskId, mode);
            const cleanValue = String(value ?? "");
            if (cleanValue) {
                window.localStorage.setItem(key, cleanValue);
            } else {
                window.localStorage.removeItem(key);
            }
        } catch (_error) {}
    }

    function syncInputWithDraft(force = false) {
        const inputEl = byId("chatInput");
        if (!inputEl) return;
        const draftKey = currentDraftKey();
        const draftValue = readDraft();
        const currentKey = inputEl.dataset.draftKey || "";
        if (force || currentKey !== draftKey || !text(inputEl.value)) {
            inputEl.value = draftValue;
        }
        inputEl.dataset.draftKey = draftKey;
    }

    function currentPanelKey(taskId = "") {
        return `${PANEL_STORAGE_KEY}:${text(taskId, text(currentView.conversation_task_id)) || "global"}`;
    }

    function readPanelState(taskId = "") {
        try {
            const raw = window.localStorage.getItem(currentPanelKey(taskId));
            const parsed = raw ? JSON.parse(raw) : {};
            return {
                taskOpen: Boolean(parsed?.taskOpen),
                logOpen: Boolean(parsed?.logOpen),
            };
        } catch (_error) {
            return { taskOpen: false, logOpen: false };
        }
    }

    function writePanelState(nextState, taskId = "") {
        try {
            const current = readPanelState(taskId);
            const merged = {
                taskOpen: Boolean(nextState?.taskOpen ?? current.taskOpen),
                logOpen: Boolean(nextState?.logOpen ?? current.logOpen),
            };
            window.localStorage.setItem(currentPanelKey(taskId), JSON.stringify(merged));
        } catch (_error) {}
    }

    function readSectionState() {
        try {
            const raw = window.localStorage.getItem(SECTION_STORAGE_KEY);
            const parsed = raw ? JSON.parse(raw) : {};
            return {
                summaryCollapsed: parsed?.summaryCollapsed !== false,
                recentCollapsed: parsed?.recentCollapsed !== false,
            };
        } catch (_error) {
            return {
                summaryCollapsed: true,
                recentCollapsed: true,
            };
        }
    }

    function writeSectionState(nextState) {
        try {
            const current = readSectionState();
            window.localStorage.setItem(SECTION_STORAGE_KEY, JSON.stringify({
                summaryCollapsed: Boolean(nextState?.summaryCollapsed ?? current.summaryCollapsed),
                recentCollapsed: Boolean(nextState?.recentCollapsed ?? current.recentCollapsed),
            }));
        } catch (_error) {}
    }

    function setSectionCollapsed(sectionKey, collapsed) {
        if (sectionKey === "summary") {
            writeSectionState({ summaryCollapsed: collapsed });
        } else if (sectionKey === "recent") {
            writeSectionState({ recentCollapsed: collapsed });
        }
    }

    function isSectionCollapsed(sectionKey) {
        const state = readSectionState();
        return sectionKey === "summary" ? state.summaryCollapsed : state.recentCollapsed;
    }

    function setNotice(message) {
        const noticeEl = byId("pageNotice");
        if (!noticeEl) return;
        const rendered = text(message);
        noticeEl.textContent = rendered;
        noticeEl.classList.toggle("visible", Boolean(rendered));
    }

    function showToast(message) {
        const toastEl = byId("floatingToast");
        if (!toastEl) return;
        const rendered = text(message);
        if (!rendered) {
            toastEl.hidden = true;
            toastEl.classList.remove("visible");
            return;
        }
        toastEl.textContent = rendered;
        toastEl.hidden = false;
        requestAnimationFrame(() => toastEl.classList.add("visible"));
        window.clearTimeout(toastTimer);
        toastTimer = window.setTimeout(() => {
            toastEl.classList.remove("visible");
            window.setTimeout(() => {
                toastEl.hidden = true;
            }, 220);
        }, 2600);
    }

    function friendlySummaryLabel(key, fallback = "") {
        const labels = {
            waiting_review: "확인 필요",
            failed_or_revision: "다시 수정",
            upload_ready: "업로드 준비",
            upload_verify_failed: "반영 다시 확인",
        };
        return text(labels[text(key)], fallback);
    }

    function friendlySummaryHint(key, fallback = "") {
        const hints = {
            waiting_review: "사람 판단이 끝나면 바로 이어집니다.",
            failed_or_revision: "막힌 작업만 다시 정리하면 됩니다.",
            upload_ready: "올릴 준비가 된 작업만 모아 봅니다.",
            upload_verify_failed: "반영 후 다시 확인할 작업입니다.",
        };
        return text(hints[text(key)], fallback);
    }

    function friendlySummaryActionHint(key, fallback = "") {
        const hints = {
            waiting_review: "눌러서 확인 필요한 작업부터 시작",
            failed_or_revision: "눌러서 다시 수정 흐름 시작",
            upload_ready: "눌러서 업로드 준비 흐름 시작",
            upload_verify_failed: "눌러서 반영 확인 흐름 시작",
        };
        return text(hints[text(key)], fallback);
    }

    function friendlyTaskStatus(task) {
        const status = text(task?.status).toUpperCase();
        const labelMap = {
            WAITING_REVIEW: "확인 필요",
            WAITING_USER_CHECK: "확인 필요",
            WAITING_APPROVAL: "확인 필요",
            REVISION_REQUESTED: "다시 수정",
            FAILED: "다시 수정",
            HOLD: "멈춤",
            READY_TO_UPLOAD: "업로드 준비",
            UPLOAD_APPROVED: "업로드 준비",
            UPLOADING: "처리 중",
            PLANNING: "처리 중",
            RUNNING: "처리 중",
            REDEBUG_RUNNING: "처리 중",
            POST_UPLOAD_VERIFY: "반영 확인",
            UPLOAD_VERIFY_FAILED: "반영 다시 확인",
            DONE: "완료",
            QUEUED: "준비 중",
        };
        return text(labelMap[status], friendlyTaskRuntimeLabel(task?.status_label || task?.step_label || task?.status, "상태 없음"));
    }

    function friendlyTaskRuntimeLabel(value, fallback = "") {
        const raw = text(value).trim();
        if (!raw) {
            return text(fallback);
        }
        const normalized = raw.replace(/[-\s]+/g, "_").replace(/__+/g, "_");
        const key = normalized.toUpperCase();
        const labelMap = {
            TASK_CREATED: "작업 생성",
            TASK_ACTION: "다음 행동 정리",
            TASK_RUNNING: "작업 실행",
            TASK_RESULT: "결과 정리",
            TASK_DONE: "완료",
            CODE_EDIT: "코드 수정 중",
            CODE_EDITING: "코드 수정 중",
            VERIFY: "검증 중",
            VERIFYING: "검증 중",
            UPLOAD_READY: "업로드 준비",
            UPLOAD_VERIFY: "반영 확인",
            WAITING_REVIEW: "확인 필요",
            WAITING_APPROVAL: "확인 필요",
            WAITING_USER_CHECK: "확인 필요",
            REVISION_REQUESTED: "다시 수정",
            FAILED: "다시 수정",
            HOLD: "멈춤",
            RUNNING: "처리 중",
            PLANNING: "계획 정리 중",
            POST_UPLOAD_VERIFY: "반영 확인",
            DONE: "완료",
            QUEUED: "준비 중",
        };
        if (labelMap[key]) {
            return labelMap[key];
        }
        if (/^[a-z0-9_:-]+$/i.test(raw)) {
            if (/task/.test(key) && /created/.test(key)) return "작업 생성";
            if (/action/.test(key)) return "다음 행동 정리";
            if (/code/.test(key) && /(edit|patch|change)/.test(key)) return "코드 수정 중";
            if (/(verify|check|review)/.test(key)) return "검증 중";
            if (/upload/.test(key)) return "업로드 준비";
            if (/(run|progress|working)/.test(key)) return "처리 중";
        }
        return raw;
    }

    function isRunningTaskStatus(task) {
        const status = text(task?.status).toUpperCase();
        if (typeof task?.is_running === "boolean") {
            return task.is_running;
        }
        return ["PLANNING", "RUNNING", "REDEBUG_RUNNING", "UPLOADING", "POST_UPLOAD_VERIFY"].includes(status);
    }

    function applyProgressHealth(task) {
        if (!task) {
            progressMonitor = { taskId: "", signature: "", stagnantPolls: 0 };
            return null;
        }
        const taskId = text(task.id);
        const running = isRunningTaskStatus(task);
        const signature = [
            taskId,
            text(task.status).toUpperCase(),
            text(task.progress_percent),
            text(task.progress_updated_at),
        ].join("|");
        if (!running || !taskId) {
            progressMonitor = { taskId: "", signature: "", stagnantPolls: 0 };
            task._progress_health = text(task.status).toUpperCase() === "DONE" ? "done" : "idle";
            task._progress_stalled = false;
            return task;
        }
        if (progressMonitor.taskId === taskId && progressMonitor.signature === signature) {
            progressMonitor.stagnantPolls += 1;
        } else {
            progressMonitor = { taskId, signature, stagnantPolls: 0 };
        }
        task._progress_stagnant_polls = progressMonitor.stagnantPolls;
        task._progress_stalled = progressMonitor.stagnantPolls >= 2;
        task._progress_health = task._progress_stalled ? "stalled" : "live";
        return task;
    }

    function taskProgressState(task) {
        const status = text(task?.status).toUpperCase();
        const map = {
            QUEUED: { percent: 15, note: "작업을 준비하고 있습니다.", ticker: ["작업을 준비하고 있습니다…", "실행 순서를 정리하고 있습니다…"] },
            PLANNING: { percent: 28, note: "계획과 다음 행동을 정리하는 중입니다.", ticker: ["실행 계획을 정리하고 있습니다…", "다음 행동을 묶고 있습니다…"] },
            WAITING_APPROVAL: { percent: 42, note: "지금은 사용자 확인이 필요합니다.", ticker: ["확인 항목을 정리하고 있습니다…", "다음 판단을 준비하고 있습니다…"] },
            WAITING_USER_CHECK: { percent: 42, note: "지금은 사용자 확인이 필요합니다.", ticker: ["확인할 포인트를 정리하고 있습니다…", "다음 판단을 준비하고 있습니다…"] },
            WAITING_REVIEW: { percent: 42, note: "지금은 사용자 확인이 필요합니다.", ticker: ["검토 대상을 정리하고 있습니다…", "바로 판단할 항목을 준비하고 있습니다…"] },
            RUNNING: { percent: 66, note: "백그라운드에서 실제 작업을 처리 중입니다.", ticker: ["처리 중입니다…", "결과를 준비하고 있습니다…", "작업 변경 사항을 정리하고 있습니다…"] },
            REDEBUG_RUNNING: { percent: 68, note: "재확인과 복구를 진행 중입니다.", ticker: ["실패 지점을 다시 확인하고 있습니다…", "복구 결과를 준비하고 있습니다…"] },
            READY_TO_UPLOAD: { percent: 82, note: "업로드 직전 확인 단계입니다.", ticker: ["업로드 준비를 확인하고 있습니다…", "마지막 점검을 진행하고 있습니다…"] },
            UPLOAD_APPROVED: { percent: 88, note: "업로드 승인 이후 반영 순서를 준비합니다.", ticker: ["반영 준비를 진행하고 있습니다…", "업로드 순서를 정리하고 있습니다…"] },
            UPLOADING: { percent: 92, note: "업로드와 반영을 진행 중입니다.", ticker: ["업로드를 진행하고 있습니다…", "반영 결과를 기다리고 있습니다…"] },
            POST_UPLOAD_VERIFY: { percent: 96, note: "반영 후 검증을 진행 중입니다.", ticker: ["반영 결과를 확인하고 있습니다…", "최종 검증을 준비하고 있습니다…"] },
            UPLOAD_VERIFY_FAILED: { percent: 78, note: "반영 후 다시 확인이 필요합니다.", ticker: ["반영 실패 원인을 정리하고 있습니다…", "다시 확인할 항목을 모으고 있습니다…"] },
            REVISION_REQUESTED: { percent: 48, note: "수정 요청이 들어와 다시 정리해야 합니다.", ticker: ["수정 요청 내용을 정리하고 있습니다…"] },
            FAILED: { percent: 46, note: "실패 원인을 다시 확인해야 합니다.", ticker: ["실패 원인을 다시 정리하고 있습니다…"] },
            HOLD: { percent: 40, note: "멈춘 이유를 먼저 확인해야 합니다.", ticker: ["멈춘 이유를 정리하고 있습니다…"] },
            DONE: { percent: 100, note: "완료되었습니다. 결과만 확인하면 됩니다.", ticker: ["완료되었습니다. 결과를 확인하세요."] },
        };
        const selected = map[status] || { percent: task ? 24 : 0, note: task ? "다음 단계로 넘어갈 준비를 합니다." : "", ticker: ["지금 상태를 정리하고 있습니다…"] };
        const serverPercent = Number(task?.progress_percent);
        const hasServerPercent = Number.isFinite(serverPercent);
        const serverTicker = Array.isArray(task?.progress_ticker_messages)
            ? task.progress_ticker_messages.map((item) => text(item)).filter(Boolean)
            : [];
        const serverRunning = typeof task?.is_running === "boolean" ? task.is_running : null;
        const serverDone = typeof task?.is_done === "boolean" ? task.is_done : null;
        const isStalled = Boolean(task?._progress_stalled);
        const percent = hasServerPercent ? serverPercent : Number(selected.percent || 0);
        const fallbackTicker = ["업데이트를 다시 확인하는 중입니다…", "진행 상태를 새로 불러오고 있습니다…"];
        const note = isStalled ? "업데이트를 다시 확인하는 중입니다." : text(task?.progress_note, selected.note);
        const ticker = isStalled
            ? fallbackTicker
            : (serverTicker.length ? serverTicker : (Array.isArray(selected.ticker) ? selected.ticker : []));
        return {
            percent: Math.max(0, Math.min(100, Number(percent || 0))),
            note,
            ticker,
            done: serverDone === null ? status === "DONE" : serverDone,
            running: serverRunning === null
                ? ["PLANNING", "RUNNING", "REDEBUG_RUNNING", "UPLOADING", "POST_UPLOAD_VERIFY"].includes(status)
                : serverRunning,
            health: isStalled ? "stalled" : ((serverDone === null ? status === "DONE" : serverDone) ? "done" : ((serverRunning === null
                ? ["PLANNING", "RUNNING", "REDEBUG_RUNNING", "UPLOADING", "POST_UPLOAD_VERIFY"].includes(status)
                : serverRunning) ? "live" : "idle")),
        };
    }

    function starterPromptTooltip(item, task) {
        if (text(item?.mode) === "new-task") {
            const labels = {
                "검토 대기부터 처리": "기존 대기 작업을 먼저 정리해서 새 작업으로 시작합니다.",
                "새 작업 바로 시작": "아무 맥락 없이 새로운 작업을 바로 시작합니다.",
                "결과부터 점검": "최근 결과를 먼저 요약받고 다음 확인을 정합니다.",
                "업로드 경로 확인": "업로드 직전 막힌 조건을 빠르게 확인합니다.",
                "이건 새 작업으로 분리": "현재 흐름과 분리해서 별도 작업으로 시작합니다.",
            };
            return text(labels[text(item?.label)], "이 버튼은 새 작업을 빠르게 시작하는 예시 명령입니다.");
        }
        if (taskProgressState(task).running) {
            return "이 버튼은 진행 중인 작업의 상태를 짧게 확인하는 질문입니다.";
        }
        if (taskProgressState(task).done) {
            return "이 버튼은 완료된 작업 결과를 다시 정리해 달라는 질문입니다.";
        }
        return "이 버튼은 현재 작업을 이어서 판단하기 위한 보조 질문입니다.";
    }

    function setSelectedComposerMode(mode) {
        selectedComposerMode = text(mode);
        if (!currentView.composer || typeof currentView.composer !== "object") {
            currentView.composer = {};
        }
        currentView.composer.selected_mode = selectedComposerMode;
        currentView.composer.mode = selectedComposerMode;
        currentView.composer.mode_label = composerModeSummary(currentView.current_task || null, selectedComposerMode);
        saveComposerMode(selectedComposerMode);
        renderComposerModeSwitch(currentView.composer || {});
    }

    function renderComposerModeSwitch(composer) {
        const wrapEl = byId("composerModeSwitch");
        if (!wrapEl) return;
        wrapEl.innerHTML = "";
        wrapEl.hidden = true;
    }

    function renderSummaryCounts(items) {
        const summarySectionEl = byId("summarySection");
        const summaryStripEl = byId("summaryStrip");
        const summaryBodyEl = byId("summarySectionBody");
        const summaryToggleButtonEl = byId("summaryToggleButton");
        if (!summaryStripEl) return;
        if (isThinBridgeMode()) {
            summaryStripEl.innerHTML = "";
            if (summarySectionEl) summarySectionEl.hidden = true;
            if (summaryBodyEl) summaryBodyEl.hidden = true;
            return;
        }
        const rows = Array.isArray(items) ? items : [];
        if (!rows.length) {
            summaryStripEl.innerHTML = "";
            if (summarySectionEl) summarySectionEl.hidden = true;
            return;
        }
        if (summarySectionEl) summarySectionEl.hidden = false;
        const isCollapsed = isSectionCollapsed("summary");
        if (summaryBodyEl) {
            summaryBodyEl.hidden = isCollapsed;
        }
        if (summaryToggleButtonEl) {
            summaryToggleButtonEl.textContent = isCollapsed ? "펼쳐 보기" : "접기";
        }
        const enabledCount = rows.filter((item) => Number(item.count || 0) > 0 && text(item.prompt_text)).length;
        if (enabledCount === 0 && !currentView.current_task) {
            summaryStripEl.innerHTML = "";
            if (summarySectionEl) summarySectionEl.hidden = true;
            return;
        }
        const emptyHint = enabledCount === 0
            ? `
                <div class="summary-inline-hint">
                    지금 바로 묶어서 처리할 대기 카드는 없습니다.
                    아래 예시 프롬프트로 새 작업을 시작하거나 최근 작업을 다시 열어 바로 이어가면 됩니다.
                </div>
            `
            : "";
        summaryStripEl.innerHTML = rows
            .map((item) => {
                const canStart = Number(item.count || 0) > 0 && text(item.prompt_text);
                return `
                <button
                    type="button"
                    class="summary-chip ${canStart ? "clickable" : ""}"
                    data-key="${escapeHtml(item.key || "")}"
                    data-summary-prompt="${escapeHtml(item.prompt_text || "")}"
                    data-summary-mode="${escapeHtml(item.prompt_mode || "new-task")}"
                    ${canStart ? "" : "disabled"}
                >
                    <div class="summary-chip-label">${escapeHtml(friendlySummaryLabel(item.key, item.label || "-"))}</div>
                    <div class="summary-chip-count">${Number(item.count || 0)}</div>
                    <div class="summary-chip-hint">${escapeHtml(friendlySummaryHint(item.key, item.hint || ""))}</div>
                    <div class="summary-chip-hint">${escapeHtml(friendlySummaryActionHint(item.key, item.action_hint || (canStart ? "눌러서 바로 시작" : "지금 시작할 항목이 없습니다.")))}</div>
                </button>
            `;
            })
            .join("") + emptyHint;
    }

    function recentTaskAttention(task) {
        if (task?.is_current) {
            return { tone: "current", badge: "현재", cta: "바로 계속", rank: 0 };
        }
        const combined = `${friendlyTaskRuntimeLabel(task?.status_label).toLowerCase()} ${friendlyTaskRuntimeLabel(task?.next_action).toLowerCase()}`;
        if (/(진행 중|수행 중|업로드 중|계획 수립 중|실행 중)/.test(combined)) {
            return { tone: "running", badge: "처리 중", cta: "상태만 확인", rank: 2 };
        }
        if (/(완료|검증이 완료|마무리)/.test(combined)) {
            return { tone: "done", badge: "완료", cta: "결과 보기", rank: 3 };
        }
        if (/(확인|검토|승인|요청|결정|진행하세요|누르세요)/.test(combined)) {
            return { tone: "action", badge: "확인 필요", cta: "바로 판단", rank: 1 };
        }
        return { tone: "idle", badge: "다음", cta: "이어 보기", rank: 4 };
    }

    function renderRecentTasks(items) {
        const stripEl = byId("recentStrip");
        const listEl = byId("recentTaskList");
        const subtitleEl = byId("recentSubtitle");
        const recentBodyEl = byId("recentSectionBody");
        const recentToggleButtonEl = byId("recentToggleButton");
        if (!stripEl || !listEl) return;
        if (isThinBridgeMode()) {
            stripEl.hidden = true;
            listEl.innerHTML = "";
            if (recentBodyEl) recentBodyEl.hidden = true;
            if (subtitleEl) subtitleEl.textContent = "";
            return;
        }
        const rows = Array.isArray(items) ? items : [];
        if (!rows.length) {
            stripEl.hidden = true;
            listEl.innerHTML = "";
            if (subtitleEl) {
                subtitleEl.textContent = "최근 작업이 생기면 운영 콘솔로 가지 않고 여기서 바로 다시 이어서 열 수 있습니다.";
            }
            return;
        }
        const orderedRows = rows
            .map((item, index) => ({ ...item, _attention: recentTaskAttention(item), _index: index }))
            .sort((a, b) => (a._attention.rank - b._attention.rank) || (a._index - b._index));
        stripEl.hidden = false;
        const isCollapsed = isSectionCollapsed("recent");
        if (recentBodyEl) {
            recentBodyEl.hidden = isCollapsed;
        }
        if (recentToggleButtonEl) {
            recentToggleButtonEl.textContent = isCollapsed ? "펼쳐 보기" : "접기";
        }
        if (subtitleEl) {
            const actionCount = orderedRows.filter((item) => item._attention?.tone === "action").length;
            const runningCount = orderedRows.filter((item) => item._attention?.tone === "running").length;
            const doneCount = orderedRows.filter((item) => item._attention?.tone === "done").length;
            if (orderedRows[0]?.is_current) {
                subtitleEl.textContent = "지금 선택된 작업부터 바로 이어가면 됩니다.";
            } else if (actionCount > 0) {
                subtitleEl.textContent = "확인 필요 작업부터 고르면 됩니다.";
            } else if (runningCount === orderedRows.length) {
                subtitleEl.textContent = "처리 중인 작업은 상태만 확인하면 됩니다.";
            } else if (doneCount > 0) {
                subtitleEl.textContent = "완료된 작업은 결과 확인용으로만 봅니다.";
            } else {
                subtitleEl.textContent = "필요한 작업 하나만 골라 이어가면 됩니다.";
            }
        }
        listEl.innerHTML = orderedRows
            .map((item) => {
                const progressState = taskProgressState(item);
                const progress = Math.max(0, Math.min(100, Number(progressState.percent || 0)));
                const stepLabel = friendlyTaskRuntimeLabel(item.step_label || item.status_label || item.next_action, "상태 확인");
                const updatedLabel = compactTimestamp(item.progress_updated_at || item.updated_at);
                return `
                <button
                    type="button"
                    class="recent-chip ${item.is_current ? "active" : ""}"
                    data-tone="${escapeHtml(item._attention?.tone || "idle")}"
                    data-recent-task-id="${escapeHtml(item.id || "")}"
                >
                    <div class="recent-chip-top">
                        <div class="recent-chip-badge">${escapeHtml(item._attention?.badge || "다음")}</div>
                        <div class="recent-chip-cta">${escapeHtml(item._attention?.cta || "이어 보기")}</div>
                    </div>
                    <div class="recent-chip-title">${escapeHtml(item.title || "제목 없는 작업")}</div>
                    <div class="recent-chip-status">${escapeHtml(stepLabel)}</div>
                    <div class="recent-chip-progress">
                        <div class="recent-chip-progress-head">
                            <span>${escapeHtml(friendlyTaskStatus(item))}</span>
                            <span>${progress}%</span>
                        </div>
                        <div class="progress-track">
                            <div class="progress-bar ${item._attention?.tone === "running" ? "animated" : ""} ${progressState.health === "stalled" ? "stalled" : ""}" style="width:${progress}%"></div>
                        </div>
                    </div>
                    <div class="recent-chip-note">최근 업데이트 · ${escapeHtml(updatedLabel)}</div>
                </button>
            `;
            })
            .join("");
    }

    function renderProjectDrawer(viewModel) {
        const listEl = byId("projectList");
        const drawerCopyEl = byId("projectDrawerCopy");
        const drawerToggleButtonEl = byId("projectDrawerToggleButton");
        const searchInputEl = byId("projectSearchInput");
        const filterWrapEl = byId("projectStageFilters");
        const summaryCardEl = byId("projectSummaryCard");
        const stageEl = byId("projectSummaryStage");
        const titleEl = byId("projectSummaryTitle");
        const goalEl = byId("projectSummaryGoal");
        const pulseEl = byId("projectSummaryPulse");
        const approvalEl = byId("projectSummaryApproval");
        const planFactEl = byId("projectSummaryPlanFact");
        const updatedEl = byId("projectSummaryUpdated");
        const stageTrackEl = byId("projectStageTrack");
        const detailsEl = byId("projectSummaryDetails");
        const summaryToggleButtonEl = byId("projectSummaryToggleButton");
        const progressValueEl = byId("projectSummaryProgressValue");
        const progressBarEl = byId("projectSummaryProgressBar");
        const nextEl = byId("projectSummaryNext");
        const planListEl = byId("projectPlanList");
        const approveButtonEl = byId("projectApproveButton");
        if (!listEl) return;
        if (isThinBridgeMode(viewModel)) {
            const drawerEl = byId("projectDrawer");
            const overlayEl = byId("projectDrawerOverlay");
            if (drawerEl) drawerEl.classList.remove("is-open");
            if (overlayEl) overlayEl.hidden = true;
            listEl.innerHTML = "";
            if (summaryCardEl) summaryCardEl.hidden = true;
            return;
        }

        const projects = Array.isArray(viewModel?.projects) ? viewModel.projects : [];
        const selectedProject = viewModel?.selected_project || null;
        const selectedId = text(viewModel?.selected_project_id || selectedProject?.id);
        const activeCount = projects.filter((project) => text(project.status).toUpperCase() === "ACTIVE").length;
        const approvalCount = projects.filter((project) => !project.approved).length;
        const searchTerm = text(projectFilterText).toLowerCase();
        const filteredProjects = projects.filter((project) => {
            const stage = text(project.status).toUpperCase();
            const stageMatch = projectFilterStage === "ALL"
                ? true
                : projectFilterStage === "DONE"
                    ? ["DONE", "HOLD"].includes(stage)
                    : stage === projectFilterStage;
            if (!stageMatch) {
                return false;
            }
            if (!searchTerm) {
                return true;
            }
            const haystack = [
                project.title,
                project.goal,
                project.next_step,
                project.latest_summary,
                project.status_hint,
                project.active_plan_title,
            ]
                .map((item) => text(item).toLowerCase())
                .join(" ");
            return haystack.includes(searchTerm);
        });

        if (drawerToggleButtonEl) {
            drawerToggleButtonEl.textContent = projects.length ? `프로젝트 ${projects.length}` : "프로젝트";
        }
        if (searchInputEl && searchInputEl.value !== projectFilterText) {
            searchInputEl.value = projectFilterText;
        }
        if (filterWrapEl) {
            filterWrapEl.querySelectorAll("[data-project-filter]").forEach((buttonEl) => {
                const key = text(buttonEl.getAttribute("data-project-filter"), "ALL");
                buttonEl.classList.toggle("active", key === projectFilterStage);
            });
        }
        if (drawerCopyEl) {
            if (!projects.length) {
                drawerCopyEl.textContent = "프로젝트를 만들면 목표, 승인, 자동 실행 흐름을 여기서 한눈에 봅니다.";
            } else if (filteredProjects.length !== projects.length) {
                drawerCopyEl.textContent = `검색 결과 ${filteredProjects.length}개 / 전체 ${projects.length}개`;
            } else if (activeCount > 0) {
                drawerCopyEl.textContent = `전체 ${projects.length}개 · 자동 실행 ${activeCount}개 · 승인 대기 ${approvalCount}개`;
            } else {
                drawerCopyEl.textContent = `전체 ${projects.length}개 · 승인 대기 ${approvalCount}개`;
            }
        }

        listEl.innerHTML = filteredProjects.length
            ? filteredProjects.map((project) => {
                const projectId = text(project.id);
                const active = projectId && projectId === selectedId;
                const progress = Math.max(0, Math.min(100, Number(project.progress_percent || 0)));
                return `
                    <button type="button" class="project-card ${active ? "active" : ""}" data-project-select="${escapeHtml(projectId)}">
                        <div class="project-card-top">
                            <span class="project-card-stage" data-tone="${escapeHtml(projectStageTone(project.status))}">${escapeHtml(project.stage_label || "기획")}</span>
                            <span>${progress}%</span>
                        </div>
                        <div class="project-card-title">${escapeHtml(project.title || "이름 없는 프로젝트")}</div>
                        <div class="project-card-next">${escapeHtml(project.workspace_brief || project.status_hint || `다음 · ${project.next_step || "다음 계획 정리"}`)}</div>
                    <div class="project-card-progress"><div class="project-card-progress-bar" style="width:${progress}%"></div></div>
                    <div class="project-card-facts">
                        <span>${escapeHtml(project.approved ? "승인됨" : "승인 전")}</span>
                        <span>${escapeHtml(project.summary_line || `작업 ${String(project.task_count || 0)}개`)}</span>
                        <span>${escapeHtml(compactTimestamp(project.updated_at))}</span>
                    </div>
                    <div class="project-card-update">${escapeHtml(compactSummaryText(project.current_task_title || project.latest_summary || project.next_step || "최근 요약 없음", 38))}</div>
                </button>
                `;
            }).join("")
            : `<div class="project-empty">${projects.length ? "조건에 맞는 프로젝트가 없습니다." : "프로젝트가 없으면 먼저 하나 만드세요."}</div>`;

        if (!selectedProject || !selectedId) {
            if (summaryCardEl) summaryCardEl.hidden = true;
            setProjectSummaryOpen(false);
            if (approveButtonEl) {
                approveButtonEl.hidden = true;
                approveButtonEl.dataset.projectId = "";
            }
            return;
        }

        if (summaryCardEl) summaryCardEl.hidden = false;
        const shouldForceOpen = !Boolean(selectedProject.approved) || text(selectedProject.status).toUpperCase() === "APPROVAL";
        if (shouldForceOpen && !projectSummaryOpen) {
            setProjectSummaryOpen(true);
        } else {
            setProjectSummaryOpen(projectSummaryOpen);
        }
        if (stageEl) stageEl.textContent = text(selectedProject.stage_label, "기획");
        if (titleEl) titleEl.textContent = text(selectedProject.title, "선택된 프로젝트");
        if (goalEl) goalEl.textContent = text(selectedProject.goal, "프로젝트 목표를 정리하세요.");
        if (pulseEl) pulseEl.textContent = projectExecutionPulse(selectedProject);
        if (approvalEl) approvalEl.textContent = selectedProject.approved ? "승인됨" : "승인 전";
        if (planFactEl) {
            const doneCount = Number(selectedProject.plan_done_count || 0);
            const totalCount = Number(selectedProject.plan_total_count || 0);
            planFactEl.textContent = totalCount ? `계획 ${doneCount}/${totalCount}` : `작업 ${text(selectedProject.task_count, "0")}개`;
        }
        if (updatedEl) updatedEl.textContent = `업데이트 ${compactTimestamp(selectedProject.updated_at)}`;
        renderProjectStageTrack(stageTrackEl, selectedProject.status);
        const progress = Math.max(0, Math.min(100, Number(selectedProject.progress_percent || 0)));
        if (progressValueEl) progressValueEl.textContent = `${progress}%`;
        if (progressBarEl) progressBarEl.style.width = `${progress}%`;
        if (nextEl) {
            const activePlanTitle = text(selectedProject.active_plan_title);
            const remainingCount = Number(selectedProject.plan_remaining_count || 0);
            const workspaceLogLine = compactSummaryText(text(selectedProject.workspace_log_line), 68);
            if (workspaceLogLine && text(selectedProject.status).toUpperCase() === "ACTIVE") {
                nextEl.textContent = workspaceLogLine;
            } else if (activePlanTitle) {
                nextEl.textContent = `지금 Codex가 하는 일: ${activePlanTitle}`;
            } else if (remainingCount > 0) {
                nextEl.textContent = `남은 단계 ${remainingCount}개 · ${text(selectedProject.next_step, "다음 계획 정리")}`;
            } else {
                nextEl.textContent = `다음 일 · ${text(selectedProject.next_step, "다음 계획 정리")}`;
            }
        }
        if (planListEl) {
            const items = Array.isArray(selectedProject.plan_items) ? selectedProject.plan_items : [];
            const visibleItems = items.filter((item) => !/DONE|COMPLETE/i.test(text(item?.status))).slice(0, 3);
            planListEl.innerHTML = visibleItems.length
                ? visibleItems.map((item) => `
                    <div class="project-plan-item">
                        <div class="project-plan-item-top">
                            <strong>${escapeHtml(item.title || "계획 항목")}</strong>
                            <span>${escapeHtml(friendlyTaskRuntimeLabel(item.status || "TODO"))}</span>
                        </div>
                        <div class="project-plan-note">${escapeHtml(item.note || "다음 단계 정리")}</div>
                    </div>
                `).join("")
                : `<div class="project-empty">남은 단계가 없으면 결과 확인만 하면 됩니다.</div>`;
        }
        if (approveButtonEl) {
            const canApprove = !Boolean(selectedProject.approved) && text(selectedProject.status).toUpperCase() !== "DONE";
            approveButtonEl.hidden = !canApprove;
            approveButtonEl.disabled = pendingRequest || !canApprove;
            approveButtonEl.textContent = canApprove ? "계획 승인 후 자동 진행" : "승인 완료";
            approveButtonEl.dataset.projectId = selectedId;
        }
        if (detailsEl) {
            detailsEl.hidden = !projectSummaryOpen;
        }
        if (summaryToggleButtonEl) {
            summaryToggleButtonEl.hidden = false;
        }
    }

    function autonomyBannerState(task, primaryAction) {
        if (!task) {
            return {
                tone: "idle",
                badge: "새 작업",
                headline: "지금은 명령만 보내면 됩니다.",
                copy: "보내면 Codex가 바로 정리합니다.",
                meta: "",
            };
        }

        const status = text(task.status).toUpperCase();
        const progress = taskProgressState(task);
        const actionLabel = text(primaryAction?.label, "다음 행동");
        const nextAction = text(task.next_action, "다음 행동을 정리하는 중입니다.");
        const statusLabel = friendlyTaskRuntimeLabel(task.progress_label || task.status_label || task.step_label || nextAction || status, "현재 상태");

        if (progress.running) {
            return {
                tone: "running",
                badge: "처리 중",
                headline: "지금은 Codex가 처리 중입니다.",
                copy: progress.health === "stalled" ? "진행률을 다시 확인하는 중입니다." : "막힘 없으면 기다리면 됩니다.",
                meta: statusLabel,
            };
        }
        if (progress.done) {
            return {
                tone: "done",
                badge: "완료",
                headline: "지금은 결과만 보면 됩니다.",
                copy: "필요하면 후속 지시만 남기면 됩니다.",
                meta: statusLabel,
            };
        }
        return {
            tone: "action",
            badge: "지금 판단",
            headline: `지금은 '${actionLabel}'만 정하면 됩니다.`,
            copy: "질문 1개 또는 기본 행동 1개면 됩니다.",
            meta: statusLabel,
        };
    }

    function stopBannerTicker() {
        window.clearInterval(bannerTickerTimer);
        bannerTickerTimer = 0;
    }

    function startBannerTicker(messages, fallbackMessage, shouldRotate) {
        const tickerEl = byId("autonomyBannerTicker");
        if (!tickerEl) return;
        const rows = Array.isArray(messages) ? messages.filter(Boolean) : [];
        const firstMessage = text(rows[0], fallbackMessage);
        tickerEl.textContent = firstMessage;
        stopBannerTicker();
        if (!shouldRotate || rows.length <= 1) {
            return;
        }
        let index = 0;
        bannerTickerTimer = window.setInterval(() => {
            index = (index + 1) % rows.length;
            tickerEl.textContent = text(rows[index], fallbackMessage);
        }, BANNER_TICK_MS);
    }

    function renderAutonomyBanner(task, primaryAction) {
        const bannerEl = byId("autonomyBanner");
        const badgeEl = byId("autonomyBannerBadge");
        const headlineEl = byId("autonomyBannerHeadline");
        const copyEl = byId("autonomyBannerCopy");
        const metaEl = byId("autonomyBannerMeta");
        const statusRowEl = byId("autonomyBannerStatusRow");
        const spinnerEl = byId("autonomyBannerSpinner");
        const tickerEl = byId("autonomyBannerTicker");
        const percentEl = byId("autonomyBannerPercent");
        const progressTrackEl = byId("autonomyBannerProgressTrack");
        const progressBarEl = byId("autonomyBannerProgressBar");
        if (!bannerEl || !badgeEl || !headlineEl || !copyEl || !metaEl) return;
        const thinBridge = isThinBridgeMode();
        const hideBridgeStatusDetails = () => {
            copyEl.textContent = "";
            copyEl.hidden = true;
            metaEl.textContent = "";
            metaEl.hidden = true;
            if (statusRowEl && spinnerEl && tickerEl && percentEl && progressTrackEl && progressBarEl) {
                statusRowEl.hidden = true;
                spinnerEl.hidden = true;
                tickerEl.textContent = "";
                percentEl.textContent = "";
                progressTrackEl.hidden = true;
                progressBarEl.style.width = "0%";
                progressBarEl.classList.remove("animated", "stalled");
                bannerEl.dataset.progressHealth = "idle";
                stopBannerTicker();
            }
        };
        const hideBridgeProgressOnly = () => {
            if (statusRowEl && spinnerEl && tickerEl && percentEl && progressTrackEl && progressBarEl) {
                statusRowEl.hidden = true;
                spinnerEl.hidden = true;
                tickerEl.textContent = "";
                percentEl.textContent = "";
                progressTrackEl.hidden = true;
                progressBarEl.style.width = "0%";
                progressBarEl.classList.remove("animated", "stalled");
                bannerEl.dataset.progressHealth = "idle";
                stopBannerTicker();
            }
        };
        if (hasPendingConfirmation()) {
            const interpretation = interpretPendingIntent(pendingConfirmationMessage());
            bannerEl.dataset.tone = "action";
            badgeEl.textContent = "이해 확인";
            headlineEl.textContent = interpretation.summary;
            if (thinBridge) {
                copyEl.textContent = `${interpretation.plan} ${interpretation.next}`;
                copyEl.hidden = false;
                metaEl.textContent = "";
                metaEl.hidden = true;
                hideBridgeProgressOnly();
                return;
            }
            copyEl.textContent = interpretation.next;
            copyEl.hidden = false;
            metaEl.textContent = "";
            metaEl.hidden = true;
            if (statusRowEl && spinnerEl && tickerEl && percentEl && progressTrackEl && progressBarEl) {
                statusRowEl.hidden = true;
                spinnerEl.hidden = true;
                tickerEl.textContent = "";
                percentEl.textContent = "";
                progressTrackEl.hidden = true;
                progressBarEl.style.width = "0%";
                progressBarEl.classList.remove("animated", "stalled");
                bannerEl.dataset.progressHealth = "idle";
                stopBannerTicker();
            }
            return;
        }
        const bridgeStateLabel = bridgeRunStateLabel(currentView);
        if (!task) {
            const bridgeCopy = bridgeStatusCopy(currentView, null);
            bannerEl.dataset.tone = "idle";
            badgeEl.textContent = "현재 상태";
            headlineEl.textContent = bridgeCopy.headline || bridgeStateLabel;
            if (thinBridge) {
                copyEl.textContent = bridgeCopy.waitHint || "한 줄 명령을 보내면 상태가 여기 표시됩니다.";
                copyEl.hidden = !copyEl.textContent;
                metaEl.textContent = text(currentView.updated_at) ? `최근 업데이트 · ${compactTimestamp(currentView.updated_at)}` : "";
                metaEl.hidden = !metaEl.textContent;
                hideBridgeProgressOnly();
                return;
            }
            copyEl.textContent = text(currentView.summary, "지시를 보내면 여기서 상태를 확인합니다.");
            copyEl.hidden = !copyEl.textContent;
            metaEl.textContent = text(currentView.updated_at) ? `최근 업데이트 · ${compactTimestamp(currentView.updated_at)}` : "";
            metaEl.hidden = !metaEl.textContent;
            if (statusRowEl && spinnerEl && tickerEl && percentEl && progressTrackEl && progressBarEl) {
                statusRowEl.hidden = true;
                spinnerEl.hidden = true;
                tickerEl.textContent = "";
                percentEl.textContent = "";
                progressTrackEl.hidden = true;
                progressBarEl.style.width = "0%";
                progressBarEl.classList.remove("animated", "stalled");
                bannerEl.dataset.progressHealth = "idle";
                stopBannerTicker();
            }
            return;
        }
        const banner = autonomyBannerState(task, primaryAction);
        const progress = taskProgressState(task);
        const bridgeCopy = bridgeStatusCopy(currentView, task);
        const headline = bridgeCopy.headline || bridgeStateLabel || text(banner.headline);
        const copy = text(
            bridgeCopy.waitHint || currentView.summary,
            progress.running
                ? "지금은 처리 중입니다."
                : progress.done
                    ? "결과만 확인하면 됩니다."
                    : text(banner.copy, "상태를 확인하면 됩니다.")
        );
        const meta = text(currentView.updated_at) ? `최근 업데이트 · ${compactTimestamp(currentView.updated_at)}` : text(banner.meta);
        bannerEl.dataset.tone = text(banner.tone, "idle");
        badgeEl.textContent = "현재 상태";
        headlineEl.textContent = headline;
        if (thinBridge) {
            copyEl.textContent = copy;
            copyEl.hidden = !copy;
            metaEl.textContent = meta;
            metaEl.hidden = !metaEl.textContent;
            hideBridgeProgressOnly();
            return;
        }
        copyEl.textContent = copy;
        copyEl.hidden = !copy;
        metaEl.textContent = meta;
        metaEl.hidden = !metaEl.textContent;
        if (statusRowEl && spinnerEl && tickerEl && percentEl && progressTrackEl && progressBarEl) {
            const hasProgress = Boolean(task);
            statusRowEl.hidden = !hasProgress;
            progressTrackEl.hidden = !hasProgress;
            spinnerEl.hidden = !progress.running;
            tickerEl.textContent = text(progress.note);
            percentEl.textContent = hasProgress ? `${progress.percent}%` : "";
            progressBarEl.style.width = `${progress.percent}%`;
            progressBarEl.classList.toggle("animated", progress.running);
            progressBarEl.classList.toggle("stalled", progress.health === "stalled");
            progressTrackEl.dataset.progressHealth = progress.health || "idle";
            bannerEl.dataset.progressHealth = progress.health || "idle";
            startBannerTicker(progress.ticker, progress.note, progress.running);
        }
    }

    function interactionCopy(task, primaryAction) {
        if (!task) {
            return {
                tone: "idle",
                attentionBadge: "새 작업 시작",
                composerHint: "한 줄 명령만 보내면 됩니다.",
                composerHelper: "Enter 실행",
                sendButtonLabel: text(currentView.composer?.send_button_label, "실행 요청"),
                sendAndRunLabel: "보내고 바로 실행",
                contextLead: "현재 작업이 생기면 여기서 바로 이어서 판단합니다.",
                summaryLabel: "현재 요약",
                nextActionLabel: "지금 바로 필요한 다음 행동",
                decisionLabel: "판단 요약",
                riskLabel: "리스크 메모",
            };
        }

        const tone = autonomyBannerState(task, primaryAction).tone;
        if (tone === "running") {
            return {
                tone,
                attentionBadge: "Codex 진행 중",
                composerHint: "지금은 상태만 보면 됩니다.",
                composerHelper: "질문 1개면 됩니다.",
                sendButtonLabel: "상태 확인 보내기",
                sendAndRunLabel: canAutoRunPrimaryAction(currentView) ? "상태 확인 보내고 바로 실행" : "상태 확인 보내기",
                contextLead: "지금은 이 흐름만 짧게 확인하면 됩니다.",
                summaryLabel: "지금 Codex가 진행 중인 일",
                nextActionLabel: "지금은 기다리면 되는 이유",
                decisionLabel: "현재 진행 기준",
                riskLabel: "막힘 징후",
            };
        }
        if (tone === "done") {
            return {
                tone,
                attentionBadge: "결과 확인",
                composerHint: "지금은 결과만 보면 됩니다.",
                composerHelper: "후속 지시만 남기세요.",
                sendButtonLabel: "결과 점검 요청",
                sendAndRunLabel: canAutoRunPrimaryAction(currentView) ? "점검 요청 보내고 바로 실행" : "결과 점검 요청",
                contextLead: "지금은 결과와 남은 확인만 보면 됩니다.",
                summaryLabel: "결과 핵심",
                nextActionLabel: "지금 내가 확인할 것",
                decisionLabel: "이번 결과 판단",
                riskLabel: "남은 리스크",
            };
        }
        return {
            tone,
            attentionBadge: "사용자 판단",
            composerHint: "지금은 판단만 하면 됩니다.",
            composerHelper: "질문 1개면 됩니다.",
            sendButtonLabel: "판단 질문 보내기",
            sendAndRunLabel: canAutoRunPrimaryAction(currentView) ? "질문 보내고 바로 실행" : "판단 질문 보내기",
            contextLead: "지금은 이 한 가지 판단만 정리하면 됩니다.",
            summaryLabel: "지금 판단에 필요한 배경",
            nextActionLabel: "지금 내가 눌러야 할 것",
            decisionLabel: "왜 지금 판단이 필요한지",
            riskLabel: "지금 막히는 조건",
        };
    }

    function composerInteractionCopy(task, primaryAction) {
        if (!task) {
            return interactionCopy(task, primaryAction);
        }
        const mode = text(selectedComposerMode, text(currentView.composer?.selected_mode || currentView.composer?.mode, "followup"));
        if (mode === "new-task") {
            return {
                composerHint: "지금 입력은 새 작업으로 분리합니다.",
                composerHelper: "현재 작업에는 붙지 않습니다.",
                sendButtonLabel: "새 작업 만들기",
                sendAndRunLabel: "새 작업 만들고 바로 실행",
            };
        }
        const copy = interactionCopy(task, primaryAction);
        return {
            composerHint: copy.composerHint,
            composerHelper: copy.composerHelper,
            sendButtonLabel: copy.sendButtonLabel,
            sendAndRunLabel: copy.sendAndRunLabel,
        };
    }

    function composerModeSummary(task, composerMode) {
        const mode = text(composerMode, text(currentView.composer?.selected_mode || currentView.composer?.mode, task ? "followup" : "new-task"));
        if (mode === "new-task") {
            return task ? "새 작업으로 분리" : "새 작업 시작";
        }
        return task ? "현재 작업 계속" : "새 작업 시작";
    }

    function focusStageRows(task) {
        const status = text(task?.status).toUpperCase();
        let currentIndex = 0;
        if (["QUEUED", "PLANNING", "WAITING_APPROVAL", "WAITING_USER_CHECK", "WAITING_REVIEW", "REVISION_REQUESTED", "FAILED", "HOLD"].includes(status)) {
            currentIndex = 1;
        } else if (["RUNNING", "REDEBUG_RUNNING", "UPLOADING"].includes(status)) {
            currentIndex = 2;
        } else if (["READY_TO_UPLOAD", "UPLOAD_APPROVED", "POST_UPLOAD_VERIFY", "UPLOAD_VERIFY_FAILED", "DONE"].includes(status)) {
            currentIndex = 3;
        }
        return [
            {
                label: "명령",
                hint: "생성",
                state: currentIndex > 0 ? "done" : "current",
            },
            {
                label: "판단",
                hint: currentIndex === 1 ? "지금" : "대기",
                state: currentIndex > 1 ? "done" : currentIndex === 1 ? "current" : "",
            },
            {
                label: "실행",
                hint: currentIndex === 2 ? "진행" : currentIndex > 2 ? "완료" : "대기",
                state: currentIndex > 2 ? "done" : currentIndex === 2 ? "current" : "",
            },
            {
                label: "검증",
                hint: currentIndex === 3 ? (status === "DONE" ? "결과" : "확인") : "최종",
                state: currentIndex === 3 ? "current" : "",
            },
        ];
    }

    function renderFocusStrip(task, primaryAction) {
        const stripEl = byId("focusStrip");
        const subtitleEl = byId("focusStripSubtitle");
        const stageTrackEl = byId("focusStageTrack");
        const planCardEl = byId("planFocusCard");
        const resultCardEl = byId("resultFocusCard");
        if (!stripEl || !stageTrackEl || !planCardEl || !resultCardEl) return;
        if (isThinBridgeMode()) {
            stripEl.hidden = true;
            stageTrackEl.innerHTML = "";
            planCardEl.innerHTML = "";
            resultCardEl.innerHTML = "";
            if (subtitleEl) subtitleEl.textContent = "";
            return;
        }
        if (!task) {
            stripEl.hidden = true;
            if (subtitleEl) {
                subtitleEl.textContent = "핵심만 보면 됩니다.";
            }
            stageTrackEl.innerHTML = "";
            planCardEl.innerHTML = "";
            resultCardEl.innerHTML = "";
            return;
        }

        const tone = autonomyBannerState(task, primaryAction).tone;
        stripEl.hidden = false;
        if (subtitleEl) {
            subtitleEl.textContent = tone === "running"
                ? "상태만 보면 됩니다."
                : tone === "done"
                    ? "결과만 보면 됩니다."
                    : "할 일만 보면 됩니다.";
        }
        stageTrackEl.innerHTML = focusStageRows(task).map((item) => `
            <div class="focus-stage ${escapeHtml(item.state)}">
                <div class="focus-stage-label">${escapeHtml(item.label)}</div>
                <div class="focus-stage-hint">${escapeHtml(item.hint)}</div>
            </div>
        `).join("");
        const planHeadline = tone === "running"
            ? "실행 중"
            : tone === "done"
                ? "결과 확인"
                : text(primaryAction?.label, "다음 행동");
        const planNote = tone === "running"
            ? "상태만 확인"
            : tone === "done"
                ? "결과만 확인"
                : "바로 진행";

        const verificationState = Number(task.open_check_count || 0) > 0
            ? `확인 ${Number(task.open_check_count || 0)}개`
            : "확인 없음";
        const resultHeadline = tone === "running"
            ? "결과 집계"
            : tone === "done"
                ? (Number(task.open_check_count || 0) > 0 ? `확인 ${Number(task.open_check_count || 0)}개 남음` : "확인 끝")
                : verificationState;
        const resultNote = Number(task.changed_file_count || 0) > 0 || Number(task.artifact_count || 0) > 0
            ? `변경 ${Number(task.changed_file_count || 0)}개 · 산출물 ${Number(task.artifact_count || 0)}개`
            : tone === "done"
                ? "산출물 확인"
                : "산출물 없음";

        planCardEl.innerHTML = `
            <div class="focus-card-title">계획</div>
            <div class="focus-card-headline">${escapeHtml(planHeadline)}</div>
            <div class="focus-card-copy">${escapeHtml(planNote)}</div>
        `;
        resultCardEl.innerHTML = `
            <div class="focus-card-title">결과</div>
            <div class="focus-card-headline">${escapeHtml(resultHeadline)}</div>
            <div class="focus-card-copy">${escapeHtml(resultNote)}</div>
        `;
    }

    function buildVisibleStarterPrompts(items, task, primaryAction) {
        const rows = Array.isArray(items) ? items : [];
        if (!task) {
            return rows;
        }
        const title = text(task.title, "현재 작업");
        const primaryLabel = text(primaryAction?.label, "다음 행동");
        const tone = autonomyBannerState(task, primaryAction).tone;
        const newTaskPrompt = rows.find((item) => text(item.mode) === "new-task") || {
            key: "new_task_parallel",
            label: "이건 새 작업으로 분리",
            text: "이건 현재 작업과 분리해서 새 작업으로 진행할게. 가장 짧은 실행 계획부터 잡아줘",
            mode: "new-task",
        };
        if (tone === "running") {
            return [
                {
                    key: "running_wait",
                    label: "지금은 기다리면 되는지",
                    text: `${title} 지금은 내가 기다리면 되는지, 막힌 지점이 있는지만 짧게 알려줘`,
                    mode: "followup",
                },
                {
                    key: "running_blocker",
                    label: "막힌 지점만 확인",
                    text: `${title} 진행 중 막힌 지점이 있으면 한 줄로 알려주고, 없으면 계속 진행 중이라고만 말해줘`,
                    mode: "followup",
                },
                {
                    key: "running_next_check",
                    label: "다음 확인 시점만",
                    text: `${title} 내가 다시 확인해야 할 다음 시점만 짧게 알려줘`,
                    mode: "followup",
                },
                newTaskPrompt,
            ];
        }
        if (tone === "done") {
            return [
                {
                    key: "done_summary",
                    label: "결과 3줄 요약",
                    text: `${title} 결과를 3줄로만 요약하고 내가 바로 확인할 것 1개만 알려줘`,
                    mode: "followup",
                },
                {
                    key: "done_verify",
                    label: "남은 확인만 정리",
                    text: `${title}에서 아직 남은 확인만 짧게 정리해줘`,
                    mode: "followup",
                },
                {
                    key: "done_next",
                    label: "새 작업으로 넘길지 판단",
                    text: `${title}는 여기서 닫아도 되는지, 아니면 새 작업으로 넘겨야 하는지 짧게 판단해줘`,
                    mode: "followup",
                },
                newTaskPrompt,
            ];
        }
        return [
            {
                key: "action_reason",
                label: "왜 지금 이 버튼을 눌러야 하는지",
                text: `${title}에서 지금 '${primaryLabel}'를 눌러야 하는 이유만 짧게 설명해줘`,
                mode: "followup",
            },
            {
                key: "action_checks",
                label: "누르기 전 확인할 것 3개",
                text: `${title}에서 '${primaryLabel}' 전에 내가 확인할 것 3개만 짧게 정리해줘`,
                mode: "followup",
            },
            {
                key: "action_block",
                label: "안 누르면 무엇이 멈추는지",
                text: `${title}에서 지금 '${primaryLabel}'를 누르지 않으면 무엇이 멈추는지 한 문장으로 알려줘`,
                mode: "followup",
            },
            newTaskPrompt,
        ];
    }

    function renderStarterPrompts(items, task, primaryAction) {
        const wrapEl = byId("starterPromptStrip");
        if (!wrapEl) return;
        if (isThinBridgeMode()) {
            wrapEl.innerHTML = "";
            wrapEl.hidden = true;
            return;
        }
        if (hasPendingConfirmation()) {
            wrapEl.innerHTML = "";
            wrapEl.hidden = true;
            return;
        }
        const rows = buildVisibleStarterPrompts(items, task, primaryAction);
        if (!rows.length) {
            wrapEl.innerHTML = "";
            wrapEl.hidden = true;
            return;
        }
        const visibleRows = task ? rows : [];
        if (!visibleRows.length) {
            wrapEl.innerHTML = "";
            wrapEl.hidden = true;
            return;
        }
        wrapEl.hidden = false;
        wrapEl.innerHTML = visibleRows
            .map((item) => `
                <button
                    type="button"
                    class="prompt-chip"
                    data-starter-prompt="${escapeHtml(item.text || "")}"
                    data-starter-mode="${escapeHtml(item.mode || "new-task")}"
                    title="${escapeHtml(starterPromptTooltip(item, task))}"
                >${escapeHtml(item.label || item.text || "")}</button>
            `)
            .join("");
    }

    function renderComposerContext(task, primaryAction) {
        const contextEl = byId("composerContextCard");
        if (!contextEl) return;
        if (isThinBridgeMode()) {
            contextEl.hidden = true;
            contextEl.innerHTML = "";
            return;
        }
        if (!task && hasPendingConfirmation()) {
            contextEl.hidden = true;
            contextEl.innerHTML = "";
            return;
        }
        if (!task) {
            contextEl.hidden = true;
            contextEl.innerHTML = "";
            return;
        }
        if (text(selectedComposerMode, "followup") === "new-task") {
            contextEl.hidden = true;
            contextEl.innerHTML = "";
            return;
        }
        const copy = interactionCopy(task, primaryAction);
        if (copy.tone === "running" && !Boolean(text(primaryAction?.action))) {
            contextEl.hidden = true;
            contextEl.innerHTML = "";
            return;
        }
        const statusLabel = escapeHtml(friendlyTaskRuntimeLabel(task.status_label || task.status, "상태 없음"));
        const primaryLabel = escapeHtml(primaryAction?.label || task.primary_action_label || "다음 행동 실행");
        const opsLabel = escapeHtml(text(currentView.ops_console_label, "현재 작업 운영 콘솔 열기"));
        const opsUrl = escapeHtml(text(currentView.ops_console_url, "/static/mobile-control-link.html"));
        const canRunPrimary = Boolean(text(primaryAction?.action)) && !Boolean(primaryAction?.disabled);
        const hasProject = Boolean(text(currentView.selected_project?.id));
        const contextLead = hasProject ? "" : escapeHtml(copy.contextLead);
        contextEl.hidden = false;
        contextEl.innerHTML = `
            <div class="composer-context-head">
                <div class="composer-context-copy">
                    <div class="composer-context-title">${escapeHtml(task.title || "현재 작업")}</div>
                    <div class="composer-context-meta">
                        <span class="status-pill">${statusLabel}</span>
                        <span class="status-pill">${escapeHtml(copy.attentionBadge)}</span>
                    </div>
                </div>
                <div class="composer-context-actions">
                    ${canRunPrimary ? `<button type="button" class="primary-button" data-run-primary-action="1">${primaryLabel}</button>` : ""}
                    <button type="button" class="outline-button" data-compose-focus-mode="new-task">새 작업으로 분리</button>
                    <a class="task-inline-link" href="${opsUrl}">${opsLabel}</a>
                </div>
            </div>
            ${contextLead ? `<div class="composer-context-next">${contextLead}</div>` : ""}
        `;
    }

    function renderTaskCard(task) {
        const taskCardEl = byId("taskCard");
        if (!taskCardEl) return;
        const bridgeCopy = bridgeStatusCopy(currentView, task);
        const summaryText = compactSummaryText(bridgeCopy.result || currentView.summary || task?.summary);
        const updatedText = text(currentView.updated_at || task?.updated_at);
        const runStateLabel = bridgeRunStateLabel(currentView);
        const commandText = text(currentView.command || task?.title, "아직 실행한 명령이 없습니다.");
        const lastError = text(currentView.last_error);
        const understandingText = compactSummaryText(bridgeCopy.understanding || `이 지시는 '${commandText}' 작업으로 이해했습니다.`, 120);
        const waitHintText = compactSummaryText(bridgeCopy.waitHint || "상태가 바뀌면 여기서 바로 확인됩니다.", 120);
        if (!task && !text(currentView.summary) && !text(currentView.command)) {
            taskCardEl.classList.remove("is-highlighted");
            taskCardEl.innerHTML = `
                <div class="task-card-empty">
                    아직 마지막 결과가 없습니다.
                    위에서 한 줄 명령을 보내면 마지막 결과 1개만 여기 남습니다.
                </div>
            `;
            return;
        }
        taskCardEl.classList.remove("is-compact");
        taskCardEl.innerHTML = `
            <div class="task-card-head">
                <div class="task-card-copy">
                    <div class="task-card-title">마지막 결과</div>
                    <div class="task-card-meta">
                        ${updatedText ? `<span class="meta-pill">업데이트 · ${escapeHtml(compactTimestamp(updatedText))}</span>` : ""}
                    </div>
                </div>
            </div>
            <div class="task-card-body">
                <div class="task-card-line">
                    <div class="task-card-label">상태</div>
                    <div class="task-card-value">${escapeHtml(runStateLabel)}</div>
                </div>
                <div class="task-card-line">
                    <div class="task-card-label">이해</div>
                    <div class="task-card-value">${escapeHtml(understandingText)}</div>
                </div>
                <div class="task-card-line">
                    <div class="task-card-label">기다림</div>
                    <div class="task-card-value">${escapeHtml(waitHintText)}</div>
                </div>
                <div class="task-card-line">
                    <div class="task-card-label">결과</div>
                    <div class="task-card-value">${escapeHtml(summaryText)}</div>
                </div>
                ${lastError ? `
                    <div class="task-card-line">
                        <div class="task-card-label">오류</div>
                        <div class="task-card-value">${escapeHtml(lastError)}</div>
                    </div>
                ` : ""}
            </div>
        `;
    }

    function renderPrimaryAction(currentTask, primaryAction) {
        const actionCardEl = byId("primaryActionCard");
        const actionTitleEl = byId("primaryActionTitle");
        const actionDescriptionEl = byId("primaryActionDescription");
        const actionButtonEl = byId("primaryActionButton");
        if (!actionCardEl || !actionTitleEl || !actionDescriptionEl || !actionButtonEl) return;
        if (isThinBridgeMode()) {
            actionCardEl.hidden = true;
            actionCardEl.setAttribute("aria-hidden", "true");
            actionTitleEl.textContent = "다음 행동";
            actionDescriptionEl.textContent = "기본 화면에서는 상태와 마지막 결과만 보여줍니다.";
            actionButtonEl.textContent = "다음 행동 숨김";
            actionButtonEl.disabled = true;
            actionButtonEl.className = "primary-button";
            return;
        }

        if (!currentTask || !primaryAction) {
            actionCardEl.hidden = true;
            actionCardEl.setAttribute("aria-hidden", "true");
            actionTitleEl.textContent = "다음 행동";
            actionDescriptionEl.textContent = "작업을 만들면 기본 행동 1개만 보입니다.";
            actionButtonEl.textContent = "다음 행동 없음";
            actionButtonEl.disabled = true;
            actionButtonEl.className = "primary-button";
            return;
        }

        actionCardEl.hidden = true;
        actionCardEl.setAttribute("aria-hidden", "true");
        actionTitleEl.textContent = "다음 행동";
        actionDescriptionEl.textContent = "기본 화면에서는 상태와 마지막 결과만 보여줍니다.";
        actionButtonEl.textContent = text(primaryAction.label, "다음 행동 실행");
        actionButtonEl.disabled = Boolean(primaryAction.disabled) || !text(primaryAction.action);
        actionButtonEl.className = `primary-button ${text(primaryAction.tone) === "warn" ? "warn" : ""}`.trim();
    }

    function renderLogEntries(entries) {
        const logListEl = byId("logList");
        if (!logListEl) return;
        const thinBridge = isThinBridgeMode();
        if (thinBridge) {
            const rows = buildThinBridgeTimelineRows();
            if (!rows.length) {
                logListEl.innerHTML = `
                    <article class="message" data-role="system">
                        <div class="message-meta"><span>시스템</span><span>-</span></div>
                        <div class="message-body">아직 대화가 없습니다. 아래 입력창에서 한 줄 지시를 보내면 여기에 쌓입니다.</div>
                    </article>
                `;
                return;
            }
            logListEl.innerHTML = rows
                .map((entry) => `
                    <article class="message" data-role="${escapeHtml(entry.role || "system")}">
                        <div class="message-meta">
                            <span>${escapeHtml(entry.label || "로그")}</span>
                            <span>${escapeHtml(entry.created_at || "")}</span>
                        </div>
                        <div class="message-body">${escapeHtml(entry.body || "-")}</div>
                        ${Array.isArray(entry.actions) && entry.actions.length
                            ? `
                                <div class="message-actions">
                                    ${entry.actions.map((action) => `
                                        <button
                                            type="button"
                                            class="${action.tone === "primary" ? "primary-button" : "outline-button"}"
                                            data-confirm-command="${escapeHtml(action.kind || "")}"
                                        >${escapeHtml(action.label || "")}</button>
                                    `).join("")}
                                </div>
                            `
                            : ""}
                    </article>
                `)
                .join("");
            logListEl.scrollTop = logListEl.scrollHeight;
            return;
        }
        const selectedProject = currentView.selected_project || null;
        const projectCopy = projectConversationCopy(selectedProject, currentView.current_task || null);
        let rows = hasPendingConfirmation()
            ? (() => {
                const interpretation = interpretPendingIntent(pendingConfirmationMessage());
                return [
                {
                    role: "user",
                    label: "나",
                    created_at: "",
                    body: pendingConfirmationMessage(),
                },
                {
                    role: "system",
                    label: "Codex",
                    created_at: "",
                    body: [interpretation.lead, interpretation.summary, interpretation.plan, interpretation.next].filter(Boolean).join("\n"),
                    actions: [
                        { kind: "run", label: "맞아요, 진행", tone: "primary" },
                        { kind: "edit", label: "다시 설명", tone: "outline" },
                    ],
                },
            ];
            })()
            : (Array.isArray(entries) ? entries : []);
        const projectLead = isThinBridgeMode() ? "" : projectLogLead(selectedProject, currentView.current_task || null);
        const firstRowBody = text(rows[0]?.body);
        if (text(projectLead) && !hasPendingConfirmation() && firstRowBody !== text(projectLead)) {
            rows = [
                {
                    role: "system",
                    label: "Codex",
                    created_at: "",
                    body: projectLead,
                },
                ...rows,
            ];
        }
        if (!rows.length) {
            logListEl.innerHTML = `
                <article class="message" data-role="system">
                    <div class="message-meta"><span>시스템</span><span>-</span></div>
                    <div class="message-body">아직 대화가 없습니다. 위에서 한 줄 지시를 보내면 바로 이어집니다.</div>
                </article>
            `;
            return;
        }
        logListEl.innerHTML = rows
            .map((entry) => `
                <article class="message" data-role="${escapeHtml(entry.role || "system")}">
                    <div class="message-meta">
                        <span>${escapeHtml(entry.label || "로그")}</span>
                        <span>${escapeHtml(entry.created_at || "")}</span>
                    </div>
                    <div class="message-body">${escapeHtml(entry.body || "-")}</div>
                    ${Array.isArray(entry.actions) && entry.actions.length
                        ? `
                            <div class="message-actions">
                                ${entry.actions.map((action) => `
                                    <button
                                        type="button"
                                        class="${action.tone === "primary" ? "primary-button" : "outline-button"}"
                                        data-confirm-command="${escapeHtml(action.kind || "")}"
                                    >${escapeHtml(action.label || "")}</button>
                                `).join("")}
                            </div>
                        `
                        : ""}
                </article>
            `)
            .join("");
        logListEl.scrollTop = logListEl.scrollHeight;
    }

    function flashTaskCompletion() {
        const taskCardEl = byId("taskCard");
        if (!taskCardEl) return;
        taskCardEl.classList.remove("is-highlighted");
        // Force reflow so repeated completion highlights still animate.
        void taskCardEl.offsetWidth;
        taskCardEl.classList.add("is-highlighted");
    }

    function maybeNotifyTaskCompletion(nextView) {
        const nextTaskId = text(nextView?.current_task?.id);
        const nextStatus = text(nextView?.current_task?.status).toUpperCase();
        const previousId = text(previousTaskSnapshot.id);
        const previousStatus = text(previousTaskSnapshot.status).toUpperCase();
        const didComplete = Boolean(
            previousId &&
            nextTaskId &&
            nextStatus === "DONE" &&
            (nextTaskId !== previousId || previousStatus !== "DONE") &&
            lastCompletionTaskId !== nextTaskId
        );
        previousTaskSnapshot = { id: nextTaskId, status: nextStatus };
        if (!didComplete) {
            return;
        }
        lastCompletionTaskId = nextTaskId;
        showToast("완료되었습니다. 마지막 결과를 확인하세요.");
        window.setTimeout(flashTaskCompletion, 80);
    }

    function stopStatePolling() {
        window.clearInterval(pollTimer);
        pollTimer = 0;
    }

    function stopStateEvents() {
        if (stateEventSource) {
            stateEventSource.close();
        }
        stateEventSource = null;
        stateEventKey = "";
    }

    function stateEventsUrl(taskId, composerMode, projectId) {
        const params = new URLSearchParams();
        params.set("conversation_task_id", taskId);
        if (composerMode) {
            params.set("composer_mode", composerMode);
        }
        if (projectId) {
            params.set("project_id", projectId);
        }
        return `/api/codex-chat/events?${params.toString()}`;
    }

    function scheduleStateEvents() {
        if (!window.EventSource || pendingRequest) {
            stopStateEvents();
            return;
        }
        const taskId = text(currentView?.conversation_task_id || currentView?.current_task?.id);
        if (!taskId) {
            stopStateEvents();
            return;
        }
        const composerMode = text(selectedComposerMode);
        const projectId = text(selectedProjectId);
        const nextKey = [taskId, composerMode, projectId].join("|");
        if (stateEventSource && stateEventKey === nextKey) {
            return;
        }
        stopStateEvents();
        stateEventKey = nextKey;
        stateEventSource = new window.EventSource(stateEventsUrl(taskId, composerMode, projectId));
        stateEventSource.addEventListener("state", (event) => {
            if (pendingRequest || document.hidden) {
                return;
            }
            try {
                renderView(JSON.parse(event.data || "{}"));
            } catch (_error) {
            }
        });
        stateEventSource.onerror = () => {
            // Keep polling as the fallback if the SSE connection is interrupted.
        };
    }

    function scheduleStatePolling() {
        stopStatePolling();
        if (pendingRequest) {
            return;
        }
        const hasTask = Boolean(text(currentView?.conversation_task_id || currentView?.current_task?.id));
        const isRunning = taskProgressState(currentView?.current_task || null).running;
        const delay = hasTask ? (isRunning ? ACTIVE_POLL_MS : IDLE_POLL_MS) : 0;
        if (!delay) {
            return;
        }
        pollTimer = window.setInterval(async () => {
            if (pendingRequest || document.hidden) {
                return;
            }
            try {
                await loadState(
                    text(currentView.conversation_task_id || currentView.current_task?.id),
                    text(selectedComposerMode),
                    text(selectedProjectId)
                );
            } catch (_error) {
            }
        }, delay);
    }

    function renderView(viewModel) {
        applyProgressHealth(viewModel?.current_task || null);
        maybeNotifyTaskCompletion(viewModel || {});
        currentView = viewModel || {};
        const thinBridge = isThinBridgeMode(currentView);
        if (rootEl) {
            rootEl.dataset.bridgeMode = thinBridge ? "thin-bridge" : "legacy-rich";
        }
        saveSelectedProjectId(text(currentView.selected_project_id || currentView.selected_project?.id));
        const preferredComposerMode = text(
            currentView.composer?.selected_mode || currentView.composer?.mode,
            text(selectedComposerMode, "new-task")
        );
        const stalledCurrentTask = Boolean(currentView.current_task?._progress_stalled);
        const stalledTaskId = text(currentView.current_task?.id);
        selectedComposerMode = stalledCurrentTask ? "new-task" : preferredComposerMode;
        if (thinBridge) {
            selectedComposerMode = "new-task";
        }
        saveConversationTaskId(currentView.conversation_task_id || "");
        saveComposerMode(selectedComposerMode);
        if (stalledCurrentTask && stalledTaskId && lastStalledTaskId !== stalledTaskId) {
            lastStalledTaskId = stalledTaskId;
            currentView.server_notice = "현재 작업 업데이트가 멈춰 새 작업 입력으로 전환했습니다. 필요하면 진행 리스트에서 다시 이어가면 됩니다.";
        } else if (!stalledCurrentTask) {
            lastStalledTaskId = "";
        }
        const hasCurrentTask = Boolean(currentView.current_task);
        if (!hasCurrentTask || selectedComposerMode === "new-task") {
            queuePanelOpen = false;
        }
        if (thinBridge) {
            renderSummaryCounts([]);
            renderRecentTasks([]);
            renderProjectDrawer({ bridge_mode: "thin-bridge" });
            renderStarterPrompts([], currentView.current_task || null, currentView.primary_action || null);
        } else {
            renderSummaryCounts(currentView.summary_counts || []);
            renderRecentTasks(currentView.recent_tasks || []);
            renderProjectDrawer(currentView);
            renderStarterPrompts(currentView.starter_prompts || [], currentView.current_task || null, currentView.primary_action || null);
        }
        renderAutonomyBanner(currentView.current_task || null, currentView.primary_action || null);
        renderFocusStrip(thinBridge ? null : (currentView.current_task || null), thinBridge ? null : (currentView.primary_action || null));
        renderComposerContext(thinBridge ? null : (currentView.current_task || null), thinBridge ? null : (currentView.primary_action || null));
        renderTaskCard(currentView.current_task || null);
        renderPrimaryAction(currentView.current_task || null, currentView.primary_action || null);
        renderLogEntries(currentView.log_entries || []);
        setNotice(currentView.server_notice || "");

        const summarySectionEl = byId("summarySection");
        const taskWorkspacePanelEl = byId("taskWorkspacePanel");
        const logWorkspacePanelEl = byId("logWorkspacePanel");
        const focusStripEl = byId("focusStrip");
        const composerContextCardEl = byId("composerContextCard");
        const recentTitleEl = rootEl?.querySelector(".recent-title");
        const recentZoneLabelEl = rootEl?.querySelector(".recent-zone-label");
        const opsConsoleLinkEl = byId("opsConsoleLink");
        const workspaceSourceGuideEl = byId("workspaceSourceGuide");
        const workspaceSourceValueEl = byId("workspaceSourceValue");
        const composerHintEl = byId("composerHint");
        const composerHelperEl = byId("composerHelper");
        const composerModeEl = byId("composerMode");
        const heroCopyEl = byId("heroCopy");
        const projectWorkspaceBarEl = byId("projectWorkspaceBar");
        const projectWorkspaceBarTitleEl = byId("projectWorkspaceBarTitle");
        const projectWorkspaceBarCopyEl = byId("projectWorkspaceBarCopy");
        const projectDrawerToggleButtonEl = byId("projectDrawerToggleButton");
        const queuePanelEl = rootEl?.querySelector(".queue-panel");
        const inputEl = byId("chatInput");
        const sendButtonEl = byId("sendButton");
        const sendAndRunButtonEl = byId("sendAndRunButton");
        const resetTaskButtonEl = byId("resetTaskButton");
        const copy = interactionCopy(currentView.current_task || null, currentView.primary_action || null);
        const composerCopy = composerInteractionCopy(currentView.current_task || null, currentView.primary_action || null);
        const pendingConfirmation = hasPendingConfirmation() && !hasCurrentTask;
        const taskTone = interactionCopy(currentView.current_task || null, currentView.primary_action || null).tone;
        const hasSummaryCounts = !thinBridge && Array.isArray(currentView.summary_counts) && currentView.summary_counts.length > 0;
        const projectCopy = thinBridge ? null : projectConversationCopy(currentView.selected_project || null, currentView.current_task || null);
        const hasProject = !thinBridge && Boolean(text(currentView.selected_project?.id));

        if (summarySectionEl) {
            summarySectionEl.hidden = !hasSummaryCounts;
            summarySectionEl.setAttribute("aria-hidden", summarySectionEl.hidden ? "true" : "false");
        }
        setQueuePanelOpen(false);
        setProjectDrawerOpen(false);
        if (projectDrawerToggleButtonEl) {
            projectDrawerToggleButtonEl.hidden = true;
        }
        if (queuePanelEl) {
            queuePanelEl.hidden = true;
            queuePanelEl.setAttribute("aria-hidden", "true");
        }

        if (taskWorkspacePanelEl) {
            taskWorkspacePanelEl.hidden = thinBridge;
            taskWorkspacePanelEl.setAttribute("aria-hidden", thinBridge ? "true" : "false");
            taskWorkspacePanelEl.classList.toggle("task-panel-muted", stalledCurrentTask);
            taskWorkspacePanelEl.classList.remove("task-panel-compact");
            taskWorkspacePanelEl.classList.add("task-panel-minimal");
        }
        if (focusStripEl) {
            focusStripEl.hidden = true;
        }
        if (composerContextCardEl) {
            composerContextCardEl.hidden = true;
            composerContextCardEl.innerHTML = "";
        }
        if (logWorkspacePanelEl) {
            logWorkspacePanelEl.hidden = thinBridge ? false : !pendingConfirmation;
        }
        const logSubtitleEl = byId("logSubtitle");
        if (logSubtitleEl) {
            logSubtitleEl.textContent = thinBridge
                ? "명령, 실행 상태, 마지막 결과가 아래에서 계속 쌓입니다."
                : pendingConfirmation ? "최초 입력의 뜻이 맞는지만 확인합니다." : "흐름이 여기 이어집니다.";
        }
        if (recentTitleEl) {
            recentTitleEl.textContent = "이어서 볼 작업";
        }
        if (recentZoneLabelEl) {
            recentZoneLabelEl.textContent = "작업 목록";
        }
        if (workspaceSourceGuideEl && workspaceSourceValueEl) {
            const source = detectWorkspaceSource();
            workspaceSourceGuideEl.dataset.tone = source.tone;
            workspaceSourceValueEl.textContent = source.label;
        }

        if (opsConsoleLinkEl) {
            opsConsoleLinkEl.href = text(currentView.ops_console_url, "/static/mobile-control-link.html");
            opsConsoleLinkEl.textContent = text(currentView.ops_console_label, "운영 콘솔 열기");
            opsConsoleLinkEl.hidden = true;
        }
        if (heroCopyEl) {
            const selectedProject = currentView.selected_project || null;
            const projectRunning = hasProject && Boolean(currentView.current_task);
            heroCopyEl.textContent = pendingConfirmation
                ? "해석만 확인하면 바로 진행합니다."
                : thinBridge && text(currentView.summary)
                    ? compactSummaryText(currentView.summary, 72)
                : projectRunning
                    ? text(selectedProject?.workspace_brief, "프로젝트를 이어갑니다.")
                    : hasProject
                        ? text(selectedProject?.workspace_state_line, "프로젝트 안에서 바로 시작합니다.")
                        : "한 줄 지시만 보내면 됩니다.";
        }
        if (projectWorkspaceBarEl && projectWorkspaceBarTitleEl && projectWorkspaceBarCopyEl) {
            const selectedProject = currentView.selected_project || null;
            const hasProject = Boolean(text(selectedProject?.id));
            projectWorkspaceBarEl.hidden = true;
            projectWorkspaceBarEl.setAttribute("aria-hidden", "true");
            if (hasProject) {
                projectWorkspaceBarTitleEl.textContent = text(selectedProject?.title, "선택 프로젝트");
                projectWorkspaceBarCopyEl.textContent = text(
                    selectedProject?.workspace_log_line || selectedProject?.workspace_state_line || selectedProject?.workspace_brief || selectedProject?.status_hint,
                    "이 프로젝트 흐름 안에서 바로 이어갑니다."
                );
            }
        }
        if (composerHintEl) {
            composerHintEl.textContent = pendingConfirmation
                ? "해석이 맞는지만 보면 됩니다."
                : "한 줄 명령만 보내면 됩니다.";
        }
        if (composerHelperEl) {
            composerHelperEl.textContent = pendingConfirmation
                ? "맞아요만 누르면 바로 진행합니다."
                : "Enter 실행";
        }
        renderComposerModeSwitch(currentView.composer || {});
        if (composerModeEl) {
            composerModeEl.textContent = pendingConfirmation
                ? "이해 확인 대기"
                : "명령 입력";
        }
        if (inputEl) {
            inputEl.placeholder = text(
                (!thinBridge ? projectCopy?.placeholder : "") || currentView.composer?.placeholder,
                "무엇을 해야 하는지 한 줄로 입력하세요."
            );
            inputEl.disabled = pendingConfirmation || pendingRequest;
        }
        if (sendButtonEl) {
            sendButtonEl.hidden = pendingConfirmation;
            sendButtonEl.disabled = pendingRequest;
            sendButtonEl.textContent = pendingConfirmation
                ? "맞아요, 진행"
                : pendingRequest
                ? "실행 중..."
                : "명령 보내기";
        }
        if (sendAndRunButtonEl) {
            sendAndRunButtonEl.hidden = true;
            sendAndRunButtonEl.disabled = pendingRequest;
            sendAndRunButtonEl.textContent = canAutoRunPrimaryAction(currentView)
                ? ((!thinBridge ? projectCopy?.sendAndRunLabel : "") || (currentView.current_task ? composerCopy.sendAndRunLabel : "보내고 바로 실행"))
                : "보내고 바로 실행";
        }
        if (resetTaskButtonEl) {
            resetTaskButtonEl.hidden = true;
            resetTaskButtonEl.disabled = pendingRequest;
            resetTaskButtonEl.textContent = pendingConfirmation
                ? "다시 설명"
                : text(currentView.new_task_label, "새 작업 시작");
        }
        syncInputWithDraft();
        scheduleStateEvents();
        scheduleStatePolling();
    }

    async function requestJson(url, options) {
        const response = await window.fetch(url, {
            cache: "no-store",
            ...(options || {}),
            headers: {
                "Cache-Control": "no-cache",
                ...((options && options.headers) || {}),
            },
        });
        const textBody = await response.text();
        let payload = null;
        try {
            payload = textBody ? JSON.parse(textBody) : {};
        } catch (_error) {
            payload = null;
        }
        if (!response.ok) {
            const detail = text(payload?.detail || textBody || `요청 실패 (${response.status})`, `요청 실패 (${response.status})`);
            throw new Error(detail);
        }
        return payload || {};
    }

    async function loadState(conversationTaskId, composerMode = "", projectId = "") {
        const taskId = text(conversationTaskId);
        const mode = text(composerMode);
        const selectedProject = text(projectId, selectedProjectId);
        const params = new URLSearchParams();
        if (taskId) {
            params.set("conversation_task_id", taskId);
        }
        if (mode) {
            params.set("composer_mode", mode);
        }
        if (selectedProject) {
            params.set("project_id", selectedProject);
        }
        const url = params.toString() ? `/api/codex-chat/state?${params.toString()}` : "/api/codex-chat/state";
        const payload = await requestJson(url, { method: "GET", credentials: "same-origin" });
        renderView(payload);
        return payload;
    }

    async function waitForRunnablePrimaryAction(conversationTaskId, composerMode = "followup", attempts = 4) {
        const taskId = text(conversationTaskId);
        if (!taskId) {
            return null;
        }
        let latestPayload = null;
        for (let index = 0; index < attempts; index += 1) {
            await new Promise((resolve) => window.setTimeout(resolve, index === 0 ? 250 : 450));
            const params = new URLSearchParams({
                conversation_task_id: taskId,
                composer_mode: text(composerMode, "followup"),
            });
            if (selectedProjectId) {
                params.set("project_id", selectedProjectId);
            }
            latestPayload = await requestJson(`/api/codex-chat/state?${params.toString()}`, {
                method: "GET",
                credentials: "same-origin",
            });
            renderView(latestPayload);
            if (canAutoRunPrimaryAction(latestPayload)) {
                return latestPayload;
            }
        }
        return latestPayload;
    }

    function setPending(flag) {
        pendingRequest = Boolean(flag);
        const sendButtonEl = byId("sendButton");
        const sendAndRunButtonEl = byId("sendAndRunButton");
        const resetTaskButtonEl = byId("resetTaskButton");
        const thinBridge = isThinBridgeMode(currentView);
        const composerCopy = composerInteractionCopy(currentView.current_task || null, currentView.primary_action || null);
        if (sendButtonEl) {
            sendButtonEl.disabled = pendingRequest;
            sendButtonEl.textContent = pendingRequest
                ? "실행 중..."
                : thinBridge
                    ? "명령 보내기"
                    : currentView.current_task
                    ? composerCopy.sendButtonLabel
                    : text(currentView.composer?.send_button_label, "실행 요청");
        }
        if (sendAndRunButtonEl) {
            sendAndRunButtonEl.disabled = pendingRequest;
            sendAndRunButtonEl.hidden = true;
            sendAndRunButtonEl.textContent = canAutoRunPrimaryAction(currentView)
                ? (currentView.current_task ? composerCopy.sendAndRunLabel : "보내고 바로 실행")
                : (currentView.current_task ? composerCopy.sendButtonLabel : "보내고 바로 실행");
        }
        if (resetTaskButtonEl) {
            resetTaskButtonEl.disabled = pendingRequest;
        }
        renderPrimaryAction(currentView.current_task || null, currentView.primary_action || null);
        const primaryActionButtonEl = byId("primaryActionButton");
        if (primaryActionButtonEl && pendingRequest) {
            primaryActionButtonEl.disabled = true;
        }
    }

    function focusBestNextAction() {
        if (isThinBridgeMode()) {
            byId("chatInput")?.focus?.();
            return;
        }
        byId("composerContextCard")?.querySelector("[data-run-primary-action]")?.focus?.();
        if (document.activeElement && document.activeElement !== document.body) {
            return;
        }
        byId("primaryActionButton")?.focus?.();
    }

    async function executeConfirmedMessage(message, options = {}) {
        const autoRunPrimary = Boolean(options?.autoRunPrimary);
        const inputEl = byId("chatInput");
        const draftTaskId = text(currentView.conversation_task_id);
        const draftMode = text(selectedComposerMode, text(currentView.composer?.selected_mode || currentView.composer?.mode));
        setPending(true);
        setNotice("");
        try {
            const payload = await requestJson("/api/codex-chat/command", {
                method: "POST",
                credentials: "same-origin",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    message,
                    conversation_task_id: text(currentView.conversation_task_id),
                    mode: text(selectedComposerMode, text(currentView.composer?.selected_mode || currentView.composer?.mode)),
                    project_id: selectedProjectId,
                }),
            });
            writeDraft("", draftTaskId, draftMode);
            pendingCommandConfirmation = null;
            if (inputEl) {
                inputEl.value = "";
            }
            renderView(payload);
            setQueuePanelOpen(false);
            if (autoRunPrimary) {
                const createdTaskId = text(payload.conversation_task_id || payload.current_task?.id);
                let runnablePayload = payload;
                let autoRunPayload = null;
                if (createdTaskId) {
                    runnablePayload = await waitForRunnablePrimaryAction(createdTaskId, "followup") || runnablePayload;
                    try {
                        autoRunPayload = await requestJson(`/api/codex-chat/tasks/${encodeURIComponent(text(runnablePayload.conversation_task_id || runnablePayload.current_task?.id || createdTaskId))}/primary-action`, {
                            method: "POST",
                            credentials: "same-origin",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ project_id: selectedProjectId }),
                        });
                    } catch (_error) {
                        autoRunPayload = null;
                    }
                }
                if (autoRunPayload) {
                    renderView(autoRunPayload);
                    setNotice(`${text(runnablePayload.current_task?.title || message, "작업")} 실행을 시작했습니다.`);
                } else if (canAutoRunPrimaryAction(runnablePayload)) {
                    const fallbackAutoRunPayload = await requestJson(`/api/codex-chat/tasks/${encodeURIComponent(text(runnablePayload.conversation_task_id || runnablePayload.current_task?.id || createdTaskId))}/primary-action`, {
                        method: "POST",
                        credentials: "same-origin",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ project_id: selectedProjectId }),
                    });
                    renderView(fallbackAutoRunPayload);
                    setNotice(`${text(runnablePayload.current_task?.title || message, "작업")} 실행을 시작했습니다.`);
                }
            }
            focusBestNextAction();
        } catch (error) {
            setNotice(error instanceof Error ? error.message : "명령 처리에 실패했습니다.");
        } finally {
            setPending(false);
            inputEl?.focus();
        }
    }

    async function submitMessage(options = {}) {
        const autoRunPrimary = Boolean(options?.autoRunPrimary);
        const inputEl = byId("chatInput");
        const message = text(inputEl?.value);
        if (!message || pendingRequest) {
            inputEl?.focus();
            return;
        }
        if (hasPendingConfirmation()) {
            setNotice("먼저 이해 확인 내용을 보고 [맞아요, 진행]을 눌러 주세요.");
            inputEl?.focus();
            return;
        }
        const shouldConfirmBeforeRun = isThinBridgeMode()
            || (!currentView.current_task && text(selectedComposerMode, "new-task") === "new-task");
        if (shouldConfirmBeforeRun) {
            pendingCommandConfirmation = { message };
            setNotice("");
            renderView(currentView);
            return;
        }
        await executeConfirmedMessage(message, { autoRunPrimary });
    }

    async function runPrimaryAction() {
        const taskId = text(currentView.conversation_task_id || currentView.current_task?.id);
        const action = text(currentView.primary_action?.action);
        if (!taskId || !action || pendingRequest) {
            return;
        }
        setPending(true);
        setNotice("");
        try {
            const payload = await requestJson(`/api/codex-chat/tasks/${encodeURIComponent(taskId)}/primary-action`, {
                method: "POST",
                credentials: "same-origin",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ project_id: selectedProjectId }),
            });
            renderView(payload);
            setQueuePanelOpen(false);
            focusBestNextAction();
        } catch (error) {
            setNotice(error instanceof Error ? error.message : "다음 행동 실행에 실패했습니다.");
        } finally {
            setPending(false);
        }
    }

    async function resetConversationTask() {
        if (hasPendingConfirmation()) {
            pendingCommandConfirmation = null;
            setNotice("설명을 다듬어 다시 입력해 주세요.");
            renderView(currentView);
            byId("chatInput")?.focus();
            return;
        }
        if (pendingRequest) {
            return;
        }
        setPending(true);
        setNotice("");
        saveConversationTaskId("");
        selectedComposerMode = "new-task";
        setQueuePanelOpen(false);
        try {
            await loadState("", "new-task", selectedProjectId);
            setQueuePanelOpen(false);
            setNotice("새 작업 모드로 전환했습니다. 다음 입력은 새 작업으로 기록됩니다.");
            byId("chatInput")?.focus();
        } catch (error) {
            setNotice(error instanceof Error ? error.message : "새 작업 모드 전환에 실패했습니다.");
        } finally {
            setPending(false);
        }
    }

    async function createProject() {
        const titleEl = byId("projectTitleInput");
        const goalEl = byId("projectGoalInput");
        const title = text(titleEl?.value);
        const goal = text(goalEl?.value);
        if (!title || !goal || pendingRequest) {
            setNotice("프로젝트 이름과 목표를 함께 입력해 주세요.");
            return;
        }
        setPending(true);
        setNotice("");
        try {
            const payload = await requestJson("/api/codex-chat/projects", {
                method: "POST",
                credentials: "same-origin",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ title, goal }),
            });
            if (titleEl) titleEl.value = "";
            if (goalEl) goalEl.value = "";
            renderView(payload);
            saveConversationTaskId("");
            setProjectDrawerOpen(false);
            setProjectCreateOpen(false);
            byId("chatInput")?.focus();
        } catch (error) {
            setNotice(error instanceof Error ? error.message : "프로젝트 생성에 실패했습니다.");
        } finally {
            setPending(false);
        }
    }

    async function approveProject(projectId) {
        const id = text(projectId);
        if (!id || pendingRequest) {
            return;
        }
        setPending(true);
        setNotice("");
        try {
            const payload = await requestJson(`/api/codex-chat/projects/${encodeURIComponent(id)}/approve`, {
                method: "POST",
                credentials: "same-origin",
                headers: { "Content-Type": "application/json" },
            });
            renderView(payload);
            if (text(payload.current_task?.id || payload.conversation_task_id)) {
                setSelectedComposerMode("followup");
            }
            setProjectDrawerOpen(false);
            setProjectCreateOpen(false);
        } catch (error) {
            setNotice(error instanceof Error ? error.message : "프로젝트 승인에 실패했습니다.");
        } finally {
            setPending(false);
        }
    }

    async function selectProject(projectId) {
        const id = text(projectId);
        if (!id || pendingRequest) {
            return;
        }
        saveSelectedProjectId(id);
        setPending(true);
        setNotice("");
        try {
            const payload = await loadState("", text(selectedComposerMode, "new-task"), id);
            if (text(payload.current_task?.id || payload.conversation_task_id)) {
                setSelectedComposerMode("followup");
            } else {
                setSelectedComposerMode("new-task");
            }
            setProjectDrawerOpen(false);
            setProjectCreateOpen(false);
            byId("chatInput")?.focus();
        } catch (error) {
            setNotice(error instanceof Error ? error.message : "프로젝트 전환에 실패했습니다.");
        } finally {
            setPending(false);
        }
    }

    function init() {
        const inputEl = byId("chatInput");
        const sendButtonEl = byId("sendButton");
        const sendAndRunButtonEl = byId("sendAndRunButton");
        const resetTaskButtonEl = byId("resetTaskButton");
        const primaryActionButtonEl = byId("primaryActionButton");
        const queueToggleButtonEl = byId("queuePanelToggleButton");
        const queueOverlayEl = byId("queuePanelOverlay");
        const projectDrawerToggleButtonEl = byId("projectDrawerToggleButton");
        const projectDrawerCloseButtonEl = byId("projectDrawerCloseButton");
        const projectDrawerOverlayEl = byId("projectDrawerOverlay");
        const projectCreateToggleButtonEl = byId("projectCreateToggleButton");
        const projectCreateButtonEl = byId("projectCreateButton");
        const projectApproveButtonEl = byId("projectApproveButton");
        const projectSearchInputEl = byId("projectSearchInput");
        const projectStageFiltersEl = byId("projectStageFilters");
        const initialViewModel = parseJsonScript("initialViewModelData") || {};
        const savedMode = loadSavedComposerMode();
        const savedProjectId = loadSavedProjectId();

        projectDrawerOpen = text(window.localStorage.getItem(PROJECT_DRAWER_STORAGE_KEY)) === "1";
        projectSummaryOpen = text(window.localStorage.getItem(PROJECT_SUMMARY_STORAGE_KEY)) === "1";
        setProjectDrawerOpen(projectDrawerOpen);
        setProjectSummaryOpen(projectSummaryOpen);
        setProjectCreateOpen(false);

        renderView(initialViewModel);

        sendButtonEl?.addEventListener("click", () => submitMessage());
        sendAndRunButtonEl?.addEventListener("click", () => submitMessage({ autoRunPrimary: true }));
        resetTaskButtonEl?.addEventListener("click", resetConversationTask);
        primaryActionButtonEl?.addEventListener("click", runPrimaryAction);
        queueToggleButtonEl?.addEventListener("click", () => setQueuePanelOpen(!queuePanelOpen));
        queueOverlayEl?.addEventListener("click", () => setQueuePanelOpen(false));
        projectDrawerToggleButtonEl?.addEventListener("click", () => setProjectDrawerOpen(!projectDrawerOpen));
        projectDrawerCloseButtonEl?.addEventListener("click", () => setProjectDrawerOpen(false));
        projectDrawerOverlayEl?.addEventListener("click", () => setProjectDrawerOpen(false));
        byId("projectSummaryToggleButton")?.addEventListener("click", () => setProjectSummaryOpen(!projectSummaryOpen));
        projectCreateToggleButtonEl?.addEventListener("click", () => setProjectCreateOpen(!projectCreateOpen));
        projectCreateButtonEl?.addEventListener("click", createProject);
        projectApproveButtonEl?.addEventListener("click", () => approveProject(projectApproveButtonEl.dataset.projectId || ""));
        projectSearchInputEl?.addEventListener("input", (event) => {
            projectFilterText = text(event?.target?.value);
            renderProjectDrawer(currentView);
        });
        projectStageFiltersEl?.addEventListener("click", (event) => {
            const buttonEl = event.target.closest("[data-project-filter]");
            if (!buttonEl) return;
            projectFilterStage = text(buttonEl.getAttribute("data-project-filter"), "ALL");
            renderProjectDrawer(currentView);
        });
        window.addEventListener("resize", () => setQueuePanelOpen(queuePanelOpen));
        rootEl?.addEventListener("click", async function (event) {
            const confirmButton = event.target.closest("[data-confirm-command]");
            if (confirmButton && !pendingRequest) {
                const action = text(confirmButton.dataset.confirmCommand);
                if (action === "run" && hasPendingConfirmation()) {
                    await executeConfirmedMessage(pendingConfirmationMessage(), { autoRunPrimary: true });
                } else if (action === "edit") {
                    pendingCommandConfirmation = null;
                    setNotice("설명을 다듬어 다시 입력해 주세요.");
                    renderView(currentView);
                    byId("chatInput")?.focus();
                }
                return;
            }
            const starterPromptButton = event.target.closest("[data-starter-prompt]");
            if (starterPromptButton && !pendingRequest) {
                const promptText = starterPromptButton.dataset.starterPrompt || "";
                const promptMode = text(starterPromptButton.dataset.starterMode, "new-task");
                try {
                    setSelectedComposerMode(promptMode);
                    renderView(currentView);
                    const inputEl = byId("chatInput");
                    if (inputEl) {
                        inputEl.value = promptText;
                        writeDraft(promptText);
                        inputEl.focus();
                        inputEl.setSelectionRange(inputEl.value.length, inputEl.value.length);
                    }
                } catch (error) {
                    setNotice(error instanceof Error ? error.message : "예시 명령 준비에 실패했습니다.");
                }
                return;
            }
            const summaryButton = event.target.closest("[data-summary-prompt]");
            if (summaryButton && !pendingRequest && !summaryButton.disabled) {
                const promptText = summaryButton.dataset.summaryPrompt || "";
                const promptMode = text(summaryButton.dataset.summaryMode, "new-task");
                try {
                    setSelectedComposerMode(promptMode);
                    renderView(currentView);
                    const inputEl = byId("chatInput");
                    if (inputEl) {
                        inputEl.value = promptText;
                        writeDraft(promptText);
                        inputEl.focus();
                        inputEl.setSelectionRange(inputEl.value.length, inputEl.value.length);
                    }
                } catch (error) {
                    setNotice(error instanceof Error ? error.message : "요약 카드 준비에 실패했습니다.");
                }
                return;
            }
            const sectionToggleButton = event.target.closest("[data-section-toggle]");
            if (sectionToggleButton) {
                const sectionKey = sectionToggleButton.dataset.sectionToggle || "";
                setSectionCollapsed(sectionKey, !isSectionCollapsed(sectionKey));
                renderView(currentView);
                return;
            }
            const panelToggleButton = event.target.closest("[data-panel-toggle]");
            if (panelToggleButton && !pendingRequest && currentView.current_task?.id) {
                const panelType = panelToggleButton.dataset.panelToggle || "";
                const current = readPanelState(currentView.current_task.id);
                if (panelType === "task") {
                    writePanelState({ taskOpen: !current.taskOpen }, currentView.current_task.id);
                    renderView(currentView);
                } else if (panelType === "log") {
                    writePanelState({ logOpen: !current.logOpen }, currentView.current_task.id);
                    renderView(currentView);
                }
                return;
            }
            const primaryActionInlineButton = event.target.closest("[data-run-primary-action]");
            if (primaryActionInlineButton && !pendingRequest) {
                runPrimaryAction();
                return;
            }
            const focusModeButton = event.target.closest("[data-compose-focus-mode]");
            if (focusModeButton && !pendingRequest) {
                const nextMode = focusModeButton.dataset.composeFocusMode || "";
                setSelectedComposerMode(nextMode);
                renderView(currentView);
                byId("chatInput")?.focus();
                return;
            }
            const recentButton = event.target.closest("[data-recent-task-id]");
            if (recentButton && !pendingRequest) {
                const taskId = recentButton.dataset.recentTaskId || "";
                setSelectedComposerMode("followup");
                try {
                    await loadState(taskId, "followup", selectedProjectId);
                    setQueuePanelOpen(false);
                    byId("chatInput")?.focus();
                } catch (error) {
                    setNotice(error instanceof Error ? error.message : "최근 작업 전환에 실패했습니다.");
                }
                return;
            }
            const projectButton = event.target.closest("[data-project-select]");
            if (projectButton && !pendingRequest) {
                await selectProject(projectButton.dataset.projectSelect || "");
                return;
            }
            const button = event.target.closest("[data-composer-mode]");
            if (!button || pendingRequest) {
                return;
            }
            const nextMode = button.dataset.composerMode || "";
            setSelectedComposerMode(nextMode);
            renderView(currentView);
        });
        inputEl?.addEventListener("keydown", function (event) {
            if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                submitMessage();
            }
        });
        inputEl?.addEventListener("input", function () {
            writeDraft(inputEl.value);
        });

        const savedTaskId = loadSavedConversationTaskId();
        const initialTaskId = text(initialViewModel.conversation_task_id);
        const preferredTaskId = savedTaskId || initialTaskId;
        const preferredMode = savedMode || text(initialViewModel.composer?.selected_mode || initialViewModel.composer?.mode);
        const preferredProjectId = savedProjectId || text(initialViewModel.selected_project_id || initialViewModel.selected_project?.id);
        if (preferredMode) {
            selectedComposerMode = preferredMode;
        }
        if (preferredProjectId) {
            saveSelectedProjectId(preferredProjectId);
        }
        loadState(preferredTaskId, preferredMode, preferredProjectId).catch((error) => {
            setNotice(error instanceof Error ? error.message : "Codex Max 상태를 불러오지 못했습니다.");
        });
        inputEl?.focus();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init, { once: true });
    } else {
        init();
    }
})();
