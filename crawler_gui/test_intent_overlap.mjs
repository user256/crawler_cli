// Dependency-free fixture/interaction coverage for the static GUI prototype.
import assert from "node:assert/strict";
import test from "node:test";
import { REPORT_DATA } from "./intent-report-fixture.mjs";
import { REPORT_DATA as THOMPSONS_REPORT_DATA } from "./thompsons-intent-report.mjs";
import {
  adaptReportData, createViewerState, pageVisible, pairVisible, selectCluster, selectPage,
} from "./intent-overlap.mjs";

test("Ticket 106 fixture is adapted with deterministic run identity", () => {
  const model = adaptReportData(REPORT_DATA, {
    id: "crawl-demo/run-2026-07-15T14:08:04Z", label: "Completed snapshot",
    artifact: "./report.html", source: "fixture",
  });
  assert.equal(model.run.id, "crawl-demo/run-2026-07-15T14:08:04Z");
  assert.equal(model.run.artifact, "./report.html");
  assert.ok(model.pages.every((page) => Array.isArray(page.coords)));
  assert.equal(model.byUrl.size, REPORT_DATA.pages.length);
});

test("Thompsons crawl export retains the reported run totals", () => {
  const model = adaptReportData(THOMPSONS_REPORT_DATA);
  assert.equal(model.pages.length, 3337);
  assert.equal(model.pairs.length, 736);
  assert.equal(model.clusters.length, 59);
  assert.equal(model.raw.summary.embedded, 2409);
  assert.match(model.raw.projection.method, /deterministic cluster layout/);
});

test("filters compose over exported values without recalculating report data", () => {
  const model = adaptReportData(REPORT_DATA);
  const state = createViewerState(model);
  const parameterised = model.pages.find((page) => page.url_class === "parameterised");
  assert.ok(parameterised);
  state.types.parameterised = false;
  assert.equal(pageVisible(parameterised, state), false);
  state.types.parameterised = true;
  state.search = "search?q=islay";
  assert.equal(pageVisible(parameterised, state), true);
  const pair = model.pairs.find((item) => item.pair_class === "time-sequenced");
  assert.ok(pair);
  state.search = "";
  state.types["time-sequenced"] = false;
  assert.equal(pairVisible(pair, state, model), false);
});

test("cluster-first navigation defaults to all data and composes with section filtering", () => {
  const model = adaptReportData(REPORT_DATA);
  const state = createViewerState(model);
  assert.equal(state.activeTab, "clusters");
  assert.equal(state.selectedCluster, "all");
  const scotland = model.pages.find((page) => page.cluster_id === "c-scotland" && page.url.includes("/scotland/"));
  const distillery = model.pages.find((page) => page.cluster_id === "c-distilleries");
  state.selectedCluster = "c-scotland";
  assert.equal(pageVisible(scotland, state), true);
  assert.equal(pageVisible(distillery, state), false);
  state.selectedSection = "/scotland";
  assert.equal(pageVisible(scotland, state), true);
  assert.equal(pageVisible(model.pages[0], state), false);
});

test("map/page/cluster interaction shares one selection state", () => {
  const model = adaptReportData(REPORT_DATA);
  const state = createViewerState(model);
  const cluster = model.clusters[1];
  const selected = selectCluster(state, model, cluster.id);
  assert.equal(selected, model.pages.find((page) => page.cluster_id === cluster.id)._index);
  assert.equal(selectPage(state, model.pages[0]), 0);
  assert.equal(selectCluster(state, model, "does-not-exist"), null);
});
