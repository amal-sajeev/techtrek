(function () {
  "use strict";

  var seatMap = [];
  var selectedSeats = [];
  var prices = { standard: 0, vip: 0, accessible: 0 };
  var sessionId = 0;
  var rowGapSet = {};
  var colGapSet = {};
  var stageCols = null;
  var totalCols = 0;
  var stageOffset = 0;
  var stageLabel = "Stage";
  var entryExitConfig = [];
  var customTypes = {};

  var STATUS_LABELS = {
    available:  "available",
    taken:      "taken — unavailable",
    selected:   "selected",
    vip:        "VIP available",
    accessible: "accessible available",
    reserved:   "reserved — VVIP"
  };

  function priceForType(type) {
    if (type === "vip") return prices.vip;
    if (type === "accessible") return prices.accessible;
    if (type && type.indexOf("custom_") === 0) {
      var ct = customTypes[type];
      if (ct && ct.price != null) return ct.price;
    }
    return prices.standard;
  }

  function isCustomType(type) {
    return type && type.indexOf("custom_") === 0;
  }

  function contrastColor(hex) {
    if (!hex || hex.charAt(0) !== "#") return "#fff";
    var r = parseInt(hex.slice(1, 3), 16) / 255;
    var g = parseInt(hex.slice(3, 5), 16) / 255;
    var b = parseInt(hex.slice(5, 7), 16) / 255;
    var lum = 0.299 * r + 0.587 * g + 0.114 * b;
    return lum > 0.5 ? "#000" : "#fff";
  }

  function init(data, pricing, sessId, gaps, stageOpts, entryExit, initialCustomTypes) {
    seatMap = data;
    if (typeof pricing === "object" && pricing !== null) {
      prices = { standard: pricing.standard || 0, vip: pricing.vip || 0, accessible: pricing.accessible || 0 };
    } else {
      prices = { standard: pricing || 0, vip: pricing || 0, accessible: pricing || 0 };
    }
    sessionId = sessId;
    selectedSeats = [];
    rowGapSet = {};
    colGapSet = {};
    stageCols = null;
    totalCols = 0;
    stageOffset = 0;
    stageLabel = "Stage";
    entryExitConfig = entryExit || [];
    customTypes = {};
    if (initialCustomTypes && initialCustomTypes.length) {
      initialCustomTypes.forEach(function (ct) {
        customTypes["custom_" + ct.id] = ct;
      });
    }
    if (gaps) {
      if (gaps.rowGaps) gaps.rowGaps.forEach(function (r) { rowGapSet[r] = true; });
      if (gaps.colGaps) gaps.colGaps.forEach(function (c) { colGapSet[c] = true; });
    }
    if (stageOpts) {
      stageCols = stageOpts.stageCols;
      totalCols = stageOpts.totalCols || 0;
      stageOffset = stageOpts.stageOffset || 0;
      stageLabel = stageOpts.stageLabel || "Stage";
    }
    render();
    updateSummary();
  }

  function render() {
    var container = document.getElementById("seat-map");
    if (!container) return;
    container.innerHTML = "";

    var maxRow = 0;
    var maxCol = 0;
    seatMap.forEach(function (s) {
      if (s.row > maxRow) maxRow = s.row;
      if (s.col > maxCol) maxCol = s.col;
    });

    var colTemplate = "24px";
    for (var ci = 1; ci <= maxCol; ci++) {
      colTemplate += " 36px";
      if (ci < maxCol && colGapSet[ci]) {
        colTemplate += " 14px";
      }
    }
    container.style.gridTemplateColumns = colTemplate;

    function gridCol(dataCol) {
      var gc = 1 + dataCol;
      for (var g = 1; g < dataCol; g++) {
        if (colGapSet[g]) gc++;
      }
      return gc;
    }

    var grid = {};
    seatMap.forEach(function (s) {
      grid[s.row + "-" + s.col] = s;
    });

    var gridRow = 1;

    for (var r = 1; r <= maxRow; r++) {
      var rowLabel = document.createElement("div");
      rowLabel.className = "seat-row-label";
      var rowChar = String.fromCharCode(64 + r);
      rowLabel.textContent = rowChar;
      rowLabel.setAttribute("aria-label", "Row " + rowChar);
      rowLabel.style.gridRow = gridRow;
      rowLabel.style.gridColumn = "1";
      container.appendChild(rowLabel);

      for (var c = 1; c <= maxCol; c++) {
        var seat = grid[r + "-" + c];
        var el = document.createElement("button");
        el.type = "button";
        el.style.gridRow = gridRow;
        el.style.gridColumn = String(gridCol(c));

        if (!seat || seat.type === "aisle") {
          el.className = "seat seat-empty-hidden";
          el.disabled = true;
          el.setAttribute("aria-hidden", "true");
          el.tabIndex = -1;
          el.style.visibility = "hidden";
          el.style.pointerEvents = "none";
        } else if (seat.status === "reserved") {
          el.className = "seat seat-reserved";
          el.disabled = true;
          el.dataset.seatId = seat.id;
          el.dataset.label  = seat.label;
          el.dataset.type   = seat.type;
          el.setAttribute("aria-label", "Seat " + seat.label + ", reserved — VVIP");
          el.setAttribute("aria-disabled", "true");
          el.setAttribute("role", "checkbox");
          el.setAttribute("aria-pressed", "false");
        } else {
          var statusClass = seat.status;
          if (seat.type === "vip"        && seat.status === "available") statusClass = "vip";
          if (seat.type === "accessible" && seat.status === "available") statusClass = "accessible";

          if (isCustomType(seat.type) && customTypes[seat.type] && seat.status === "available") {
            el.className = "seat seat-custom";
            el.style.backgroundColor = customTypes[seat.type].colour;
            el.style.color = contrastColor(customTypes[seat.type].colour);
            var ctIcon = customTypes[seat.type].icon;
            if (ctIcon) {
              el.textContent = ctIcon;
              el.style.fontSize = ".75rem";
            }
          } else {
            el.className = "seat seat-" + statusClass;
          }
          el.dataset.seatId = seat.id;
          el.dataset.label  = seat.label;
          el.dataset.type   = seat.type;

          var ctName = (isCustomType(seat.type) && customTypes[seat.type]) ? customTypes[seat.type].name : null;
          var typeLabel = ctName ? ctName + ", " : (seat.type !== "standard" ? seat.type + ", " : "");
          var stLabel = STATUS_LABELS[statusClass] || seat.status;
          el.setAttribute("aria-label", "Seat " + seat.label + ", " + typeLabel + stLabel);
          el.setAttribute("aria-pressed", "false");
          el.setAttribute("role", "checkbox");

          if (seat.status === "taken") {
            el.disabled = true;
            el.setAttribute("aria-disabled", "true");
          } else if (seat.status === "available") {
            el.addEventListener("click", handleSeatClick);
          }
        }

        container.appendChild(el);
      }

      gridRow++;
      if (rowGapSet[r]) gridRow++;
    }

    var stageEl = document.getElementById("seat-stage");
    requestAnimationFrame(function () {
      if (stageEl) {
        var effectiveCols = (stageCols != null && stageCols >= 1 && stageCols <= maxCol) ? stageCols : maxCol;

        var rowLabels = container.querySelectorAll(".seat-row-label");
        var dataSeats = container.querySelectorAll(".seat");
        if (rowLabels.length && dataSeats.length) {
          var containerRect = container.getBoundingClientRect();
          var firstLabel = rowLabels[0].getBoundingClientRect();
          var labelRight = firstLabel.right - containerRect.left;

          var firstSeat = null, lastSeat = null;
          dataSeats.forEach(function (s) {
            if (s.style.visibility === "hidden") return;
            var r = s.getBoundingClientRect();
            if (!firstSeat || r.left < firstSeat.left) firstSeat = r;
            if (!lastSeat || r.right > lastSeat.right) lastSeat = r;
          });

          if (firstSeat && lastSeat) {
            var dataLeft = firstSeat.left - containerRect.left;
            var dataRight = lastSeat.right - containerRect.left;
            var dataWidth = dataRight - dataLeft;
            var colW = dataWidth / maxCol;

            var sw = effectiveCols * colW;
            stageEl.style.width = Math.round(sw) + "px";
            stageEl.style.marginLeft = Math.round(dataLeft + stageOffset * colW) + "px";
          }
        }

        stageEl.style.display = "flex";
        stageEl.style.justifyContent = "center";
        stageEl.style.alignItems = "center";
        stageEl.style.boxSizing = "border-box";

        var stageLabelEl = stageEl.querySelector(".stage-label") || stageEl;
        if (stageLabelEl.childNodes.length > 0 && stageLabel) {
          stageLabelEl.textContent = stageLabel;
        }
      }

      renderEntryExitPicker(container, maxRow, maxCol);
      fitToViewport();
      adjustWrapperForMarkers();
    });
  }

  function renderEntryExitPicker(seatContainer, maxRow, maxCol) {
    var anchor = document.getElementById("picker-marker-anchor");
    if (!anchor) return;
    anchor.querySelectorAll(".picker-entry-exit").forEach(function (el) { el.remove(); });

    if (!entryExitConfig || !entryExitConfig.length) return;

    entryExitConfig.forEach(function (marker) {
      var el = document.createElement("div");
      el.className = "picker-entry-exit marker-" + marker.type;
      el.textContent = marker.label || marker.type;
      el.title = marker.type.charAt(0).toUpperCase() + marker.type.slice(1) + ": " + (marker.label || "");
      el.style.position = "absolute";
      el.style.transform = "translate(-50%, -50%)";
      el.style.left = (marker.x != null ? marker.x : 50) + "%";
      el.style.top = (marker.y != null ? marker.y : 0) + "%";

      anchor.appendChild(el);
    });
  }

  function adjustWrapperForMarkers() {
    var wrapper = document.getElementById("seat-map-wrapper");
    var anchor = document.getElementById("picker-marker-anchor");
    if (!wrapper || !anchor) return;

    wrapper.style.paddingTop = "";
    wrapper.style.paddingBottom = "";
    wrapper.style.paddingLeft = "";
    wrapper.style.paddingRight = "";

    requestAnimationFrame(function () {
      var wrapperRect = wrapper.getBoundingClientRect();
      var markers = anchor.querySelectorAll(".picker-entry-exit");
      if (!markers.length) return;

      var extraTop = 0, extraBottom = 0, extraLeft = 0, extraRight = 0;
      markers.forEach(function (m) {
        var r = m.getBoundingClientRect();
        var ot = wrapperRect.top - r.top;
        if (ot > 0) extraTop = Math.max(extraTop, ot);
        var ob = r.bottom - wrapperRect.bottom;
        if (ob > 0) extraBottom = Math.max(extraBottom, ob);
        var ol = wrapperRect.left - r.left;
        if (ol > 0) extraLeft = Math.max(extraLeft, ol);
        var or2 = r.right - wrapperRect.right;
        if (or2 > 0) extraRight = Math.max(extraRight, or2);
      });

      var cs = getComputedStyle(wrapper);
      var padT = parseFloat(cs.paddingTop);
      var padB = parseFloat(cs.paddingBottom);
      var padL = parseFloat(cs.paddingLeft);
      var padR = parseFloat(cs.paddingRight);

      var buf = 16;
      if (extraTop > 0) wrapper.style.paddingTop = (padT + extraTop + buf) + "px";
      if (extraBottom > 0) wrapper.style.paddingBottom = (padB + extraBottom + buf) + "px";
      if (extraLeft > 0) wrapper.style.paddingLeft = (padL + extraLeft + buf) + "px";
      if (extraRight > 0) wrapper.style.paddingRight = (padR + extraRight + buf) + "px";
    });
  }

  function fitToViewport() {
    var scalable = document.getElementById("seat-map-scalable");
    var wrapper = document.getElementById("seat-map-wrapper");
    if (!scalable || !wrapper) return;

    scalable.style.transform = "none";
    scalable.style.marginBottom = "0";

    var wrapperRect = wrapper.getBoundingClientRect();
    var wrapperStyles = getComputedStyle(wrapper);
    var padTop = parseFloat(wrapperStyles.paddingTop);
    var padBottom = parseFloat(wrapperStyles.paddingBottom);
    var padLeft = parseFloat(wrapperStyles.paddingLeft);
    var padRight = parseFloat(wrapperStyles.paddingRight);
    var borderTop = parseFloat(wrapperStyles.borderTopWidth) || 0;
    var borderBottom = parseFloat(wrapperStyles.borderBottomWidth) || 0;

    var legend = wrapper.querySelector(".seat-legend");
    var legendH = 0;
    if (legend) {
      legendH = legend.offsetHeight + parseFloat(getComputedStyle(legend).marginTop || 0);
    }

    var contentTop = wrapperRect.top + borderTop + padTop;
    var availH = window.innerHeight - contentTop - padBottom - borderBottom - legendH - 16;
    var availW = wrapperRect.width - padLeft - padRight;

    if (availH < 100) return;

    var naturalW = scalable.scrollWidth;
    var naturalH = scalable.scrollHeight;

    var scaleW = availW / naturalW;
    var scaleH = availH / naturalH;
    var scale = Math.min(scaleW, scaleH, 1);

    if (scale < 1) {
      scalable.style.transform = "scale(" + scale.toFixed(4) + ")";
      scalable.style.marginBottom = -(naturalH * (1 - scale)).toFixed(1) + "px";
    }

    syncSummaryHeight(wrapper);
  }

  function syncSummaryHeight(wrapper) {
    var summary = document.getElementById("booking-summary");
    if (!summary || !wrapper) return;
    if (window.innerWidth <= 900) {
      summary.style.maxHeight = "";
      return;
    }
    summary.style.maxHeight = wrapper.offsetHeight + "px";
  }

  function handleSeatClick(e) {
    var btn = e.currentTarget;
    var seatId = parseInt(btn.dataset.seatId);
    var label  = btn.dataset.label;

    var idx = selectedSeats.findIndex(function (s) { return s.id === seatId; });

    if (idx >= 0) {
      selectedSeats.splice(idx, 1);
      btn.classList.remove("seat-selected");
      btn.style.backgroundColor = "";
      var t = btn.dataset.type || "standard";
      if (isCustomType(t) && customTypes[t]) {
        btn.classList.add("seat-custom");
        btn.style.backgroundColor = customTypes[t].colour;
        btn.style.color = contrastColor(customTypes[t].colour);
      } else if (t === "vip") {
        btn.classList.add("seat-vip");
      } else if (t === "accessible") {
        btn.classList.add("seat-accessible");
      } else {
        btn.classList.add("seat-available");
      }
      btn.setAttribute("aria-pressed", "false");
      btn.setAttribute("aria-label", btn.getAttribute("aria-label").replace("selected", "available"));
    } else {
      var sType = btn.dataset.type || "standard";
      selectedSeats.push({ id: seatId, label: label, type: sType });
      btn.classList.remove("seat-available", "seat-vip", "seat-accessible", "seat-custom");
      btn.style.backgroundColor = "";
      btn.classList.add("seat-selected", "seat-pulse");
      btn.setAttribute("aria-pressed", "true");
      btn.setAttribute("aria-label", "Seat " + label + ", selected");
      setTimeout(function () { btn.classList.remove("seat-pulse"); }, 400);
    }

    updateSummary();
  }

  function updateSummary() {
    var countEl    = document.getElementById("selected-count");
    var listEl     = document.getElementById("selected-list");
    var totalEl    = document.getElementById("selected-total");
    var submitBtn  = document.getElementById("confirm-seats-btn");
    var seatInput  = document.getElementById("seat-ids-input");
    var panel      = document.getElementById("booking-summary");

    if (countEl) countEl.textContent = selectedSeats.length;

    var grandTotal = 0;
    selectedSeats.forEach(function (s) { grandTotal += priceForType(s.type); });

    if (totalEl) totalEl.textContent = "\u20B9" + grandTotal.toFixed(0);

    if (listEl) {
      listEl.innerHTML = "";
      selectedSeats.forEach(function (s) {
        var seatPrice = priceForType(s.type);
        var typeName = (isCustomType(s.type) && customTypes[s.type]) ? customTypes[s.type].name : s.type;
        var typeTag = typeName !== "standard" ? ' <span class="seat-type-tag">' + typeName.toUpperCase() + '</span>' : '';
        var seatLabelStyle = ' style="color:var(--seat-available)"';
        if (s.type === "vip") {
          seatLabelStyle = ' style="color:var(--seat-vip)"';
        } else if (s.type === "accessible") {
          seatLabelStyle = ' style="color:var(--seat-accessible)"';
        } else if (isCustomType(s.type) && customTypes[s.type]) {
          seatLabelStyle = ' style="color:' + customTypes[s.type].colour + '"';
        }
        var li = document.createElement("li");
        li.className = "selected-seat-item";
        li.innerHTML =
          '<span class="seat-label-chip"><span class="seat-number"' + seatLabelStyle + '>' + s.label + "</span>" + typeTag + "</span>" +
          '<span class="seat-price">\u20B9' + seatPrice.toFixed(0) + "</span>";
        listEl.appendChild(li);
      });
    }

    if (seatInput) {
      seatInput.value = selectedSeats.map(function (s) { return s.id; }).join(",");
    }

    if (submitBtn) {
      var isEmpty = selectedSeats.length === 0;
      submitBtn.disabled = isEmpty;
      submitBtn.setAttribute("aria-disabled", isEmpty ? "true" : "false");
    }

    if (panel) {
      panel.classList.toggle("summary-visible", selectedSeats.length > 0);
    }
  }

  var resizeTimer;
  window.addEventListener("resize", function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      fitToViewport();
      adjustWrapperForMarkers();
    }, 120);
  });

  window.SeatPicker = { init: init };
})();
