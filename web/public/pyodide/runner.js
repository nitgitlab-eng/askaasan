// Runs learner / creator Python inside <iframe sandbox="allow-scripts" src="/pyodide/runner.html">
// (see src/activities/pyodide.ts). That frame has an opaque origin: no app cookies, storage, access token or
// parent DOM. It only receives code and sends back printed output, both through postMessage.
(function () {
  "use strict";
  // The self-hosted runtime sits next to pyodide.js (runner.html picks the versioned folder). Fetches from this
  // opaque-origin frame are cross-origin, so nginx serves /pyodide/ with Access-Control-Allow-Origin: *.
  var script = document.querySelector('script[src$="/pyodide.js"]');
  var INDEX = script ? script.src.replace(/pyodide\.js$/, "") : "";
  var py = null;
  function reply(msg) {
    parent.postMessage(msg, "*"); // only printed output leaves the frame
  }
  try {
    loadPyodide({ indexURL: INDEX }).then(
      function (p) {
        py = p;
        reply({ type: "ready" });
      },
      function (e) {
        reply({ type: "failed", error: String((e && e.message) || e) });
      },
    );
  } catch (e) {
    reply({ type: "failed", error: String((e && e.message) || e) }); // pyodide.js didn't load
  }
  addEventListener("message", function (e) {
    var d = e.data || {};
    if (e.source !== parent || d.type !== "run" || !py) return;
    var out = "";
    var collect = { batched: function (s) { out += s + "\n"; } };
    py.setStdout(collect);
    py.setStderr(collect);
    py.runPythonAsync(String(d.code)).then(
      function () {
        reply({ type: "result", id: d.id, stdout: out });
      },
      function (err) {
        reply({ type: "result", id: d.id, stdout: out, error: String((err && err.message) || err) });
      },
    );
  });
})();
