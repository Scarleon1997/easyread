/* 设置 → 问 AI：阅读页右侧能选的模型。和“翻译”页同一套样子：
   上面一排卡片是名单里的模型（点一下设为新对话默认，右上角 ⋯ 改名、换模型、删除），最后一张是“添加”；
   添加或修改时，下面出现和“翻译”页一样的来源卡片（Claude Code / Codex / API 接口）和模型选择；API 的表单见 settings-api.js。
   API 的 Key 和翻译共用。 */
(function (PR) {
  "use strict";
  const T = PR.settingsTabs;
  const kindOf = (m) => (m.engine === "openai" ? "api" : m.engine);
  const isApi = (k) => k === "api";
  const root = () => PR.$("#settingsDlg");

  function cardsHtml(s) {
    const list = s.chat.models;
    return '<div class="engine-cards mc-cards">' + list.map((m, i) => {
      const def = s.chat.default === m.id;
      const badge = m.ready === false ? '<span class="badge bad" title="' + PR.esc(m.hint || "") + '">' + PR.esc(m.hint || "还不能用") + "</span>"
        : def ? '<span class="badge ok">新对话默认</span>' : "";
      return '<div class="mc' + (def ? " on" : "") + (s.editing === m.id ? " editing" : "") + (m.ready === false ? " off" : "") + '" data-cm="default" data-i="' + i + '" role="button" tabindex="0" title="设为新对话默认">' +
        '<button class="mc-more" data-cm="more" data-i="' + i + '" title="改、删">' + PR.icon("more", "sm") + "</button>" +
        "<b>" + PR.esc(m.label || m.name) + "</b>" + PR.esc([m.source, m.detail].filter(Boolean).join(" · ")) + badge + "</div>";
    }).join("") +
      '<div class="mc add' + (s.editing === "new" ? " editing" : "") + '" data-cm="add" role="button" tabindex="0">' + PR.icon("plus") + "<b>添加模型</b>Claude、GPT、Command Code，或各家 API</div></div>";
  }

  function formHtml(s) {
    const f = s.form;
    const card = (k, title, text) => '<button data-cmk="' + k + '" class="' + (f.kind === k ? "on" : "") + '"><b>' + title + "</b>" + text + "</button>";
    let h = '<div class="mc-form"><h4 class="set-h">' + (s.editing === "new" ? "添加一个模型" : "修改“" + PR.esc(f.name || autoName(s, f)) + "”") + "</h4>" +
      '<div class="engine-cards small">' +
      card("claude", "Claude Code", "本机已登录的 Claude") + card("codex", "Codex CLI", "本机已登录的 ChatGPT") +
      card("cmdc", "Command Code", "本机已登录的 Command Code") +
      card("api", "API 接口", "DeepSeek、智谱、Ollama、自定义地址等") + "</div>";
    if (f.kind === "claude" || f.kind === "codex" || f.kind === "cmdc") {
      h += '<label class="field"><span>模型</span>' + PR.cliModelSelect(s, f.kind, f.model, 'id="cmModel"', f.kind !== "claude") + "</label>" +
        '<p class="hint">' + (f.kind === "claude" ? "Opus / Sonnet 自动用 Claude Code 支持的最新版；新模型出来后运行 <code>claude update</code>。"
          : f.kind === "cmdc" ? "名单来自 <code>cmdc --list-models</code>；留空跟随 Command Code 默认。"
          : (PR.cliModelDesc(s, "codex", f.model) ? PR.esc(PR.cliModelDesc(s, "codex", f.model)) + "<br>" : "") + "名单和 Codex 里 <code>/model</code> 看到的一样。") + "</p>";
    } else {
      h += PR.apiForm.html(s, f, { keyProp: "key", vision: false });
    }
    return h + '<label class="field"><span>显示的名字（可不填）</span><input class="input" id="cmName" value="' + PR.esc(f.name) + '" placeholder="' + PR.esc(autoName(s, f)) + '"></label>' +
      '<div class="cm-form-acts"><span class="hint">' + (isApi(f.kind) ? "Key 和“翻译”页共用，每家只填一次。" : "") + '</span><span class="grow"></span>' +
      '<button class="btn sm" data-cm="cancel">取消</button><button class="btn sm accent" data-cm="ok">' + (s.editing === "new" ? "加进名单" : "改好了") + "</button></div></div>";
  }
  function autoName(s, f) {
    if (f.kind === "claude" || f.kind === "codex" || f.kind === "cmdc") {
      const o = PR.cliModelOptions(s, f.kind, f.model, f.kind !== "claude").find(([v]) => v === (f.model || ""));
      if (!o) return f.kind === "claude" ? "Claude" : f.kind === "cmdc" ? "Command Code" : "GPT";
      const inner = o[1].match(/^跟随.*（(.+)）$/);  // “跟随 Codex 默认（GPT-6-Astra）”→ GPT-6-Astra
      return inner ? inner[1] : o[1].replace(/（.*$/, "");
    }
    const p = s.presets.find((x) => x.id === f.preset);
    return f.model ? PR.apiModelName(s, f.preset, f.model) : p ? p.name : "模型";
  }
  function readForm(s) {
    const f = s.form;
    if (!f) return;
    const v = (id) => { const el = PR.$("#" + id); return el ? el.value.trim() : null; };
    if (isApi(f.kind)) PR.apiForm.read(root(), f, "key");
    else if (v("cmModel") !== null) f.model = v("cmModel");
    if (v("cmName") !== null) f.name = v("cmName");
  }
  function startForm(s, m) {
    const p = m && s.presets.find((x) => x.id === m.preset);
    s.form = m ? { kind: kindOf(m), model: m.model || "", preset: m.preset || "", base_url: m.base_url || (p ? p.base_url : ""), api: m.api || (p && p.api) || "chat", vision: false,
      name: m.name === m.label || m.name === "GPT" ? "" : m.name || "", key: "" }
      : { kind: "claude", model: "opus", preset: "", base_url: "", api: "", name: "", key: "" };
    s.fetchMsg = null; s.apiTyping = false;
  }

  T.chat = {
    render(s) {
      if (!s.chat) return '<p class="hint">读不到模型名单。</p>';
      return '<p class="set-lead">阅读页右侧“问 AI”可以选的模型。点一张卡片，设为新对话默认用的；读的时候在对话框左下角随时换。</p>' +
        cardsHtml(s) + (s.editing ? formHtml(s) : "") +
        '<p class="hint" style="margin-top:14px">每次提问会带上：你正在读的段落、你引用的几段、摘要和术语表。问到“标红的”“划线”“我的笔记”时，才会找出对应颜色的标记一起发过去。</p>';
    },
    sync(s) { readForm(s); },
    change(e, s) {
      if (s.form && isApi(s.form.kind)) return PR.apiForm.change(e, s, s.form, "key", root());
      if (e.target.id === "cmModel" && e.target.tagName === "SELECT") { readForm(s); return true; }  // 换了模型，说明和默认名字跟着变
      return false;
    },
    click(e, s) {
      const k = e.target.closest("[data-cmk]");
      if (k && s.form) {
        readForm(s);
        const f = s.form, kind = k.dataset.cmk;
        if (kind === f.kind) return false;
        Object.assign(f, { kind, model: kind === "claude" ? "opus" : "", name: "", key: "", base_url: "", api: "" });
        s.fetchMsg = null; s.apiTyping = false;
        if (isApi(kind)) {  // 先给一家：翻译那边用的 API，没有就 DeepSeek
          const o = s.cfg.openai;
          PR.apiForm.pick(s, f, s.cfg.engine === "openai" && o.preset ? o.preset : "deepseek", "key");
        }
        return true;
      }
      if (s.form && isApi(s.form.kind) && e.target.closest("[data-af-preset], [data-fetch-models]")) {
        readForm(s);
        return PR.apiForm.click(e, s, s.form, "key", root());
      }
      const b = e.target.closest("[data-cm]");
      if (!b) return false;
      const i = +b.dataset.i, list = s.chat.models, act = b.dataset.cm;
      if (act === "more") {
        const m = list[i];
        PR.menu(b, [
          { label: "修改", icon: "edit", fn: () => { readForm(s); s.editing = m.id; startForm(s, m); PR.settingsRender(); } },
          { label: "往前挪", icon: "back", disabled: i === 0, fn: () => { list.splice(i - 1, 0, list.splice(i, 1)[0]); PR.settingsRender(); } },
          "-",
          { label: "从名单里删掉", icon: "trash", fn: async () => {
            if (list.length <= 1) return PR.toast("至少留一个模型");
            if (!(await PR.confirm({ title: "删掉“" + (m.label || m.name) + "”？", body: "只是从“问 AI”的名单里拿掉，已有的对话不受影响。", ok: "删掉", danger: true }))) return;
            const at = list.indexOf(m); if (at >= 0) list.splice(at, 1);
            if (s.chat.default === m.id) s.chat.default = list[0].id;
            if (s.editing === m.id) { s.editing = null; s.form = null; }
            PR.settingsRender();
          } },
        ]);
        return false;
      }
      if (act === "default") { if (s.chat.default === list[i].id) return false; s.chat.default = list[i].id; }
      if (act === "add") { readForm(s); s.editing = "new"; startForm(s); }
      if (act === "cancel") { s.editing = null; s.form = null; }
      if (act === "ok") {
        readForm(s);
        const f = s.form, api = isApi(f.kind);
        const p = s.presets.find((x) => x.id === f.preset);
        if (api && !p && !f.base_url) { PR.toast("填接口地址"); return false; }
        if (api && !f.model) { PR.toast("填一个模型名"); return false; }
        const typed = f.key && !f.key.startsWith("••••") ? f.key : "";
        if (api && p && p.key && !PR.apiHasKey(s, f.preset) && !typed) { PR.toast("这家要填 API Key"); return false; }
        if (api && typed) (s.chatKeys = s.chatKeys || {})[f.preset] = typed;
        const name = f.name || autoName(s, f);
        const m = { engine: api ? "openai" : f.kind, preset: api ? f.preset : "",
          base_url: api && (!p || f.base_url !== p.base_url) ? f.base_url : "", api: api && (!p || f.api !== (p.api || "chat")) ? f.api : "", model: f.model, name, label: name,
          source: api ? (p ? p.name : "自定义地址") : ({ claude: "Claude Code", codex: "Codex CLI", cmdc: "Command Code" }[f.kind] || ""),
          detail: f.model || (f.kind === "cmdc" ? "跟随 Command Code 默认" : "跟随 Codex 默认"), ready: true };
        if (s.editing === "new") list.push(Object.assign(m, { id: "m" + Date.now().toString(36) }));
        else Object.assign(list.find((x) => x.id === s.editing), m);
        s.editing = null; s.form = null;
      }
      return true;
    },
  };
})(window.PR);
