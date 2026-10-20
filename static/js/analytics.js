"use strict";

const initial = document.querySelector("#analytics-initial");
const live = document.querySelector("#live-analytics");
if (initial && live) {
  const svgNode = (name, attrs, text) => {
    const node = document.createElementNS("http://www.w3.org/2000/svg", name);
    Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const drawChart = timeline => {
    const svg = svgNode("svg", { viewBox: "0 0 850 210", role: "img", "aria-label": "Successful redirects by date" });
    const max = Math.max(4, ...timeline.map(point => point.total));
    for (let i = 0; i <= 4; i++) {
      const y = 170 - i * 38;
      svg.append(svgNode("line", { x1: 32, x2: 830, y1: y, y2: y, class: "grid-line" }));
      svg.append(svgNode("text", { x: 4, y: y + 4 }, String(Math.round(max * i / 4))));
    }
    const points = timeline.map((point, index) => [40 + index * 785 / Math.max(timeline.length - 1, 1), 170 - point.total / max * 152]);
    const path = points.map((point, index) => `${index ? "L" : "M"}${point[0]},${point[1]}`).join(" ");
    if (points.length) {
      svg.append(svgNode("path", { d: `${path} L ${points.at(-1)[0]},170 L ${points[0][0]},170 Z`, class: "area" }));
      svg.append(svgNode("path", { d: path, class: "line" }));
      points.forEach((point, i) => {
        const circle = svgNode("circle", { cx: point[0], cy: point[1], r: timeline.length > 30 ? 2 : 3.5 });
        circle.append(svgNode("title", {}, `${timeline[i].day}: ${timeline[i].total} redirects`));
        svg.append(circle);
        const interval = Math.ceil(timeline.length / 7);
        if (i % interval === 0 || i === points.length - 1) svg.append(svgNode("text", { x: point[0], y: 198, "text-anchor": "middle" }, timeline[i].day.slice(5)));
      });
    }
    document.querySelector("#timeline").replaceChildren(svg);
    const rows = timeline.map(point => {
      const row = document.createElement("tr");
      [point.day, point.total].forEach(value => { const cell = document.createElement("td"); cell.textContent = value; row.append(cell); });
      return row;
    });
    document.querySelector("#timeline-table").replaceChildren(...rows);
  };
  const breakdown = (id, rows, field, fallback = "Unknown") => {
    const container = document.querySelector(id);
    if (!container) return;
    const elements = rows.map(row => {
      const div = document.createElement("div");
      const label = document.createElement("span"); label.textContent = row[field] || fallback;
      const count = document.createElement("strong"); count.textContent = row.total;
      div.append(label, count); return div;
    });
    if (!elements.length) { const p = document.createElement("p"); p.className = "muted"; p.textContent = "No data yet."; elements.push(p); }
    container.replaceChildren(...elements);
  };
  const refresh = data => {
    Object.entries(data.counts).forEach(([key, value]) => document.querySelectorAll(`[data-metric="${key}"]`).forEach(node => { node.textContent = value; }));
    drawChart(data.timeline);
    breakdown("#traffic-devices", data.devices, "device");
    breakdown("#traffic-campaigns", data.campaigns, "link__campaign__name", "Unassigned");
    breakdown("#traffic-referrers", data.referrers, "referrer_host", "Direct / unknown");
    breakdown("#traffic-browsers", data.browsers, "browser");
    breakdown("#traffic-countries", data.countries, "country");
    breakdown("#traffic-tags", data.tags, "link__tags__name");
    breakdown("#traffic-sources", data.sources, "source");
    const top = data.top_links.map(item => {
      const tr = document.createElement("tr"), td = document.createElement("td"), count = document.createElement("td"), a = document.createElement("a"), small = document.createElement("small");
      a.href = `/links/${item.link__id}/`; a.textContent = item.link__title;
      small.textContent = `/${item.link__alias}`; count.textContent = item.total;
      td.append(a, small); tr.append(td, count); return tr;
    });
    if (top.length) document.querySelector("#top-links").replaceChildren(...top);
    const alerts = data.alerts.map(item => {
      const p = document.createElement("p"), a = document.createElement("a"), badge = document.createElement("span");
      a.href = `/links/${item.id}/`; a.textContent = item.title;
      badge.className = "badge"; badge.textContent = `${item.status} / rule limit`;
      p.append(a, " ", badge); return p;
    });
    if (!alerts.length) { const p = document.createElement("p"); p.className = "muted"; p.textContent = "No paused, expired, or exhausted links in this selection."; alerts.push(p); }
    document.querySelector("#link-alerts").replaceChildren(...alerts);
  };
  refresh(JSON.parse(initial.textContent));
  let refreshing = false;
  setInterval(async () => {
    if (document.hidden || refreshing) return;
    refreshing = true;
    const status = document.querySelector("#refresh-status");
    try {
      const response = await fetch(live.dataset.endpoint + window.location.search, { headers: { Accept: "application/json" }, credentials: "same-origin" });
      if (!response.ok) throw new Error("Refresh unavailable");
      refresh(await response.json()); status.textContent = "";
    } catch { status.textContent = "· reconnecting"; }
    finally { refreshing = false; }
  }, 15000);
}
