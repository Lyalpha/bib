/* First-party GoatCounter beacon: page path only. No cookies, screen size, or referrer. */
(function () {
  var script = document.currentScript;
  var endpoint = script && script.getAttribute("data-goatcounter");
  if (!endpoint) return;
  if (navigator.doNotTrack === "1" || navigator.doNotTrack === "yes") return;
  var url =
    endpoint +
    (endpoint.indexOf("?") >= 0 ? "&" : "?") +
    "p=" +
    encodeURIComponent(location.pathname || "/") +
    "&rnd=" +
    Date.now();
  var img = new Image();
  img.referrerPolicy = "no-referrer";
  img.alt = "";
  img.src = url;
})();
