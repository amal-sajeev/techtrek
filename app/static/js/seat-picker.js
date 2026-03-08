(function () {
  "use strict";

  var seatMap = [];
  var selectedSeats = [];
  var pricePerSeat = 0;
  var sessionId = 0;
  var rowGapSet = {};
  var colGapSet = {};

  var STATUS_LABELS = {
    available:  "available",
    taken:      "taken — unavailable",
    selected:   "selected",
    vip:        "VIP available",
    accessible: "accessible available"
  };

  function init(data, price, sessId, gaps) {
    seatMap = data;
    pricePerSeat = price;
    sessionId = sessId;
    selectedSeats = [];
    rowGapSet = {};
    colGapSet = {};
    if (gaps) {
      if (gaps.rowGaps) gaps.rowGaps.forEach(function (r) { rowGapSet[r] = true; });
      if (gaps.colGaps) gaps.colGaps.forEach(function (c) { colGapSet[c] = true; });
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

    container.style.setProperty("--seat-cols", maxCol);

    var grid = {};
    seatMap.forEach(function (s) {
      grid[s.row + "-" + s.col] = s;
    });

    for (var r = 1; r <= maxRow; r++) {
      var rowLabel = document.createElement("div");
      rowLabel.className = "seat-row-label";
      if (rowGapSet[r]) rowLabel.classList.add("seat-row-gap-below");
      var rowChar = String.fromCharCode(64 + r);
      rowLabel.textContent = rowChar;
      rowLabel.setAttribute("aria-label", "Row " + rowChar);
      container.appendChild(rowLabel);

      for (var c = 1; c <= maxCol; c++) {
        var seat = grid[r + "-" + c];
        var el = document.createElement("button");
        el.type = "button";

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

        if (colGapSet[c]) el.classList.add("seat-col-gap-right");
        if (rowGapSet[r]) el.classList.add("seat-row-gap-below");

        container.appendChild(el);
      }
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
      selectedSeats.push({ id: seatId, label: label });
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
    if (totalEl) totalEl.textContent = "$" + (selectedSeats.length * pricePerSeat).toFixed(2);

    if (listEl) {
      listEl.innerHTML = "";
      selectedSeats.forEach(function (s) {
        var li = document.createElement("li");
        li.className = "selected-seat-item";
        li.innerHTML =
          '<span class="seat-label-chip">' + s.label + "</span>" +
          '<span class="seat-price">$' + pricePerSeat.toFixed(2) + "</span>";
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

  window.SeatPicker = { init: init };
})();
