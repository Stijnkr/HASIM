/* HASIM Lovelace cards: price chart + scenario comparison. No dependencies. */
(() => {
  const css = `
    :host { display: block; }
    ha-card { padding: 16px; box-sizing: border-box; }
    .hdr { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; margin-bottom: 8px; }
    .title { font-size: 16px; font-weight: 500; color: var(--primary-text-color); }
    .big { font-size: 28px; font-weight: 500; color: var(--primary-text-color); }
    .small { font-size: 12px; color: var(--secondary-text-color); }
    .stats { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 8px; }
    .stat b { color: var(--primary-text-color); font-weight: 500; }
    svg { width: 100%; height: auto; display: block; overflow: visible; }
    .axis { font-size: 10px; fill: var(--secondary-text-color); }
    .grid { stroke: var(--divider-color); stroke-width: 1; }
    .sep { stroke: var(--secondary-text-color); stroke-dasharray: 4 3; }
    .now { stroke: var(--primary-color); stroke-width: 2; }
    .bar { opacity: 0.85; } .bar:hover { opacity: 1; }
    .bar.cur { stroke: var(--primary-color); stroke-width: 2; opacity: 1; }
    .lbl { font-size: 11px; fill: var(--primary-text-color); }
    .lbl.muted { fill: var(--secondary-text-color); }
    .row { display: grid; grid-template-columns: minmax(120px, 1fr) 3fr; align-items: center; gap: 12px; margin: 6px 0; }
    .name { font-size: 13px; color: var(--primary-text-color); }
    .name.best { font-weight: 600; }
    .track { position: relative; height: 22px; }
    .fill { position: absolute; top: 2px; height: 18px; border-radius: 4px; background: var(--secondary-text-color); opacity: .6; }
    .fill.best { background: var(--success-color, #43a047); opacity: 1; }
    .fill.neg { background: var(--info-color, #039be5); }
    .val { position: absolute; top: 3px; font-size: 12px; color: var(--primary-text-color); white-space: nowrap; }
    .zero { position: absolute; top: 0; bottom: 0; width: 1px; background: var(--divider-color); }
    .empty { color: var(--secondary-text-color); font-style: italic; }
  `;

  const fmt = (v, d = 4) => (v === null || v === undefined || isNaN(v) ? "–" : Number(v).toFixed(d));
  const money = (v, cur) => (v === null || v === undefined || isNaN(v) ? "–" : `${cur} ${Number(v).toFixed(0)}`);
  const hh = (iso) => { const d = new Date(iso); return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`; };

  class HasimPriceCard extends HTMLElement {
    setConfig(config) {
      if (!config.today) throw new Error("hasim-price-card: 'today' entity is required");
      this._config = config;
    }
    set hass(hass) { this._hass = hass; this._render(); }
    getCardSize() { return 5; }
    static getStubConfig() { return { today: "", tomorrow: "", current: "" }; }

    _slots() {
      const c = this._config, h = this._hass;
      const get = (id) => (id && h.states[id]) ? h.states[id] : null;
      const today = get(c.today), tomorrow = get(c.tomorrow);
      const slots = [];
      for (const [st, day] of [[today, 0], [tomorrow, 1]]) {
        const prices = st && st.attributes && Array.isArray(st.attributes.prices) ? st.attributes.prices : [];
        for (const p of prices) slots.push({ start: p.start, price: Number(p.price), spot: Number(p.spot), day });
      }
      return { slots, today, tomorrow, current: get(c.current) };
    }

    _render() {
      if (!this._hass || !this._config) return;
      if (!this.shadowRoot) this.attachShadow({ mode: "open" });
      const lang = (this._hass.language || "en").startsWith("nl");
      const t = lang
        ? { title: "Dynamische prijs", today: "vandaag", tomorrow: "morgen", avg: "gem.", min: "min", max: "max", now: "nu", none: "Nog geen prijzen beschikbaar.", unit: "€/kWh" }
        : { title: "Dynamic price", today: "today", tomorrow: "tomorrow", avg: "avg", min: "min", max: "max", now: "now", none: "No prices available yet.", unit: "€/kWh" };
      const { slots, today, tomorrow, current } = this._slots();
      const unit = (today && today.attributes.unit_of_measurement) || t.unit;
      const title = this._config.title || t.title;
      if (!slots.length) {
        this.shadowRoot.innerHTML = `<style>${css}</style><ha-card><div class="hdr"><div class="title">${title}</div></div><div class="empty">${t.none}</div></ha-card>`;
        return;
      }
      const W = 600, H = 200, padL = 36, padR = 8, padT = 10, padB = 24;
      const n = slots.length, bw = (W - padL - padR) / n;
      const prices = slots.map((s) => s.price);
      const maxP = Math.max(...prices, 0.01), minP = Math.min(...prices, 0);
      const y = (v) => padT + (H - padT - padB) * (1 - (v - minP) / (maxP - minP || 1));
      const sorted = [...prices].sort((a, b) => a - b);
      const p33 = sorted[Math.floor(n / 3)], p66 = sorted[Math.floor((2 * n) / 3)];
      const color = (v) => (v <= p33 ? "var(--success-color, #43a047)" : v <= p66 ? "var(--warning-color, #ffa600)" : "var(--error-color, #db4437)");
      const now = Date.now();
      let curIdx = -1;
      slots.forEach((s, i) => { const st = new Date(s.start).getTime(); const nx = i + 1 < n ? new Date(slots[i + 1].start).getTime() : st + 900000; if (now >= st && now < nx) curIdx = i; });

      let bars = "", labels = "", grid = "", sep = "";
      const steps = 4;
      for (let g = 0; g <= steps; g++) {
        const v = minP + ((maxP - minP) * g) / steps, yy = y(v);
        grid += `<line class="grid" x1="${padL}" x2="${W - padR}" y1="${yy}" y2="${yy}"/>`;
        labels += `<text class="axis" x="${padL - 4}" y="${yy + 3}" text-anchor="end">${v.toFixed(2)}</text>`;
      }
      slots.forEach((s, i) => {
        const x = padL + i * bw, y0 = y(Math.max(s.price, 0)), y1 = y(Math.min(s.price, 0));
        const h = Math.max(1, y1 - y0);
        bars += `<rect class="bar${i === curIdx ? " cur" : ""}" x="${x + 0.5}" y="${y0}" width="${Math.max(bw - 1, 1)}" height="${h}" fill="${color(s.price)}" rx="1"><title>${hh(s.start)}  ${fmt(s.price)} ${unit} (spot ${fmt(s.spot)})</title></rect>`;
        const d = new Date(s.start);
        if (d.getMinutes() === 0 && d.getHours() % 6 === 0) {
          labels += `<text class="axis" x="${x}" y="${H - padB + 12}" text-anchor="start">${String(d.getHours()).padStart(2, "0")}</text>`;
        }
        if (s.day === 1 && (i === 0 || slots[i - 1].day === 0)) {
          sep += `<line class="sep" x1="${x}" x2="${x}" y1="${padT}" y2="${H - padB}"/><text class="lbl muted" x="${x + 4}" y="${padT + 10}">${t.tomorrow}</text>`;
        }
      });
      if (curIdx >= 0) {
        const x = padL + curIdx * bw + bw / 2;
        sep += `<line class="now" x1="${x}" x2="${x}" y1="${padT}" y2="${H - padB}"/>`;
      }
      const stat = (st, label) => st && st.attributes && st.attributes.available
        ? `<div class="stat small">${label}: ${t.avg} <b>${fmt(st.attributes.average)}</b> · ${t.min} <b>${fmt(st.attributes.min)}</b> · ${t.max} <b>${fmt(st.attributes.max)}</b></div>` : "";
      const cur = current && current.state && !isNaN(current.state) ? `<div class="big">${fmt(current.state)} <span class="small">${unit}</span></div>` : "";
      this.shadowRoot.innerHTML = `<style>${css}</style><ha-card>
        <div class="hdr"><div class="title">${title}</div>${cur}</div>
        <div class="stats">${stat(today, t.today)}${stat(tomorrow, t.tomorrow)}</div>
        <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${grid}${bars}${sep}${labels}</svg>
      </ha-card>`;
    }
  }

  class HasimScenarioCard extends HTMLElement {
    setConfig(config) {
      if (!config.entity) throw new Error("hasim-scenario-card: 'entity' is required");
      this._config = config;
    }
    set hass(hass) { this._hass = hass; this._render(); }
    getCardSize() { return 3; }
    static getStubConfig() { return { entity: "" }; }

    _render() {
      if (!this._hass || !this._config) return;
      if (!this.shadowRoot) this.attachShadow({ mode: "open" });
      const lang = (this._hass.language || "en").startsWith("nl");
      const t = lang
        ? { title: "Jaarkosten per scenario", sub: (d) => `schatting op basis van ${d} dagen`, none: "Nog geen simulatie." }
        : { title: "Yearly cost per scenario", sub: (d) => `estimate based on ${d} days`, none: "No simulation yet." };
      const st = this._hass.states[this._config.entity];
      const title = this._config.title || t.title;
      const cur = this._config.currency || "€";
      const costs = st && st.attributes && st.attributes.annual_costs;
      if (!st || !costs) {
        this.shadowRoot.innerHTML = `<style>${css}</style><ha-card><div class="hdr"><div class="title">${title}</div></div><div class="empty">${t.none}</div></ha-card>`;
        return;
      }
      const ranking = st.attributes.ranking || Object.keys(costs);
      const vals = ranking.map((k) => Number(costs[k]));
      const maxAbs = Math.max(...vals.map(Math.abs), 1);
      const posMax = Math.max(0, ...vals), negMin = Math.min(0, ...vals);
      const span = posMax - negMin || 1;
      const zeroPct = ((0 - negMin) / span) * 100;
      const name = (k) => {
        try { const s = this._hass.formatEntityState ? this._hass.formatEntityState(st, k) : k; return s || k; } catch (e) { return k; }
      };
      let rows = "";
      ranking.forEach((k, i) => {
        const v = Number(costs[k]);
        const w = (Math.abs(v) / span) * 100;
        const left = v >= 0 ? zeroPct : zeroPct - w;
        const best = i === 0;
        rows += `<div class="row"><div class="name${best ? " best" : ""}">${name(k)}</div>
          <div class="track"><div class="zero" style="left:${zeroPct}%"></div>
          <div class="fill${best ? " best" : ""}${v < 0 ? " neg" : ""}" style="left:${left}%;width:${Math.max(w, 0.5)}%"></div>
          <div class="val" style="left:${Math.min(v >= 0 ? zeroPct + w : zeroPct, 85) + 1}%">${money(v, cur)}</div></div></div>`;
      });
      this.shadowRoot.innerHTML = `<style>${css}</style><ha-card>
        <div class="hdr"><div class="title">${title}</div><div class="small">${t.sub(st.attributes.days)}</div></div>${rows}</ha-card>`;
      void maxAbs;
    }
  }

  if (!customElements.get("hasim-price-card")) customElements.define("hasim-price-card", HasimPriceCard);
  if (!customElements.get("hasim-scenario-card")) customElements.define("hasim-scenario-card", HasimScenarioCard);
  window.customCards = window.customCards || [];
  window.customCards.push(
    { type: "hasim-price-card", name: "HASIM price chart", description: "Day-ahead price bars for today and tomorrow" },
    { type: "hasim-scenario-card", name: "HASIM scenario comparison", description: "Yearly cost per contract/battery scenario" },
  );
})();
