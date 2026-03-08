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

  var STATUS_LABELS = {
    available:  "available",
    taken:      "taken — unavailable",
    selected:   "selected",
    vip:        "VIP available",
    accessible: "accessible available"
  };

  function priceForType(type) {
    if (type === "vip") return prices.vip;
    if (type === "accessible") return prices.accessible;
    return prices.standard;
  }

  function init(data, pricing, sessId, gaps, stageOpts) {
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
    if (gaps) {
      if (gaps.rowGaps) gaps.rowGaps.forEach(function (r) { rowGapSet[r] = true; });
      if (gaps.colGaps) gaps.colGaps.forEach(function (c) { colGapSet[c] = true; });
    }
    if (stageOpts) {
      stageCols = stageOpts.stageCols;
      totalCols = stageOpts.totalCols || 0;
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
          el.className = "seat seat-aisle";
          el.disabled = true;
          el.setAttribute("aria-hidden", "true");
          el.tabIndex = -1;
        } else {
          var statusClass = seat.status;
          if (seat.type === "vip"        && seat.status === "available") statusClass = "vip";
          if (seat.type === "accessible" && seat.status === "available") statusClass = "accessible";

          el.className = "seat seat-" + statusClass;
          el.dataset.seatId = seat.id;
          el.dataset.label  = seat.label;
          el.dataset.type   = seat.type;

          var typeLabel = seat.type !== "standard" ? seat.type + ", " : "";
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

        var stageWidth = 24;
        for (var ci = 1; ci <= effectiveCols; ci++) {
          stageWidth += 5 + 36;
          if (ci < maxCol && colGapSet[ci]) {
            stageWidth += 14;
          }
        }

        stageEl.style.width = stageWidth + "px";
        stageEl.style.display = "flex";
        stageEl.style.justifyContent = "center";
        stageEl.style.alignItems = "center";
        stageEl.style.boxSizing = "border-box";
      }

      fitToViewport();
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
  }

  function handleSeatClick(e) {
    var btn = e.currentTarget;
    var seatId = parseInt(btn.dataset.seatId);
    var label  = btn.dataset.label;

    var idx = selectedSeats.findIndex(function (s) { return s.id === seatId; });

    if (idx >= 0) {
      selectedSeats.splice(idx, 1);
      btn.classList.remove("seat-selected");
      var t = btn.dataset.type || "standard";
      if (t === "vip")        btn.classList.add("seat-vip");
      else if (t === "accessible") btn.classList.add("seat-accessible");
      else                    btn.classList.add("seat-available");
      btn.setAttribute("aria-pressed", "false");
      btn.setAttribute("aria-label", btn.getAttribute("aria-label").replace("selected", "available"));
    } else {
      var sType = btn.dataset.type || "standard";
      selectedSeats.push({ id: seatId, label: label, type: sType });
      btn.classList.remove("seat-available", "seat-vip", "seat-accessible");
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
        var typeTag = s.type !== "standard" ? ' <span class="seat-type-tag">' + s.type.toUpperCase() + '</span>' : '';
        var li = document.createElement("li");
        li.className = "selected-seat-item";
        li.innerHTML =
          '<span class="seat-label-chip">' + s.label + typeTag + "</span>" +
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
    resizeTimer = setTimeout(fitToViewport, 120);
  });

  window.SeatPicker = { init: init };
})();
