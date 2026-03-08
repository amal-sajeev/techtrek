(function () {
  "use strict";

  var seatMap = [];
  var selectedSeats = [];
  var pricePerSeat = 0;
  var sessionId = 0;

  function init(data, price, sessId) {
    seatMap = data;
    pricePerSeat = price;
    sessionId = sessId;
    selectedSeats = [];
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
      var key = s.row + "-" + s.col;
      grid[key] = s;
    });

    for (var r = 1; r <= maxRow; r++) {
      var rowLabel = document.createElement("div");
      rowLabel.className = "seat-row-label";
      rowLabel.textContent = String.fromCharCode(64 + r);
      container.appendChild(rowLabel);

      for (var c = 1; c <= maxCol; c++) {
        var key = r + "-" + c;
        var seat = grid[key];
        var el = document.createElement("button");

        if (!seat || seat.type === "aisle") {
          el.className = "seat seat-aisle";
          el.disabled = true;
        } else {
          el.className = "seat seat-" + seat.status;
          if (seat.type === "vip" && seat.status === "available") {
            el.classList.add("seat-vip");
          }
          if (seat.type === "accessible" && seat.status === "available") {
            el.classList.add("seat-accessible");
          }
          el.dataset.seatId = seat.id;
          el.dataset.label = seat.label;
          el.title = seat.label + " (" + seat.type + ")";

          if (seat.status === "taken") {
            el.disabled = true;
          } else if (seat.status === "available") {
            el.addEventListener("click", handleSeatClick);
          }
        }

        el.textContent = seat && seat.type !== "aisle" ? seat.label.split("")[seat.label.length - 1] : "";
        container.appendChild(el);
      }
    }
  }

  function handleSeatClick(e) {
    var btn = e.currentTarget;
    var seatId = parseInt(btn.dataset.seatId);
    var label = btn.dataset.label;

    var idx = selectedSeats.findIndex(function (s) {
      return s.id === seatId;
    });

    if (idx >= 0) {
      selectedSeats.splice(idx, 1);
      btn.classList.remove("seat-selected");
      btn.classList.add("seat-available");
    } else {
      selectedSeats.push({ id: seatId, label: label });
      btn.classList.remove("seat-available");
      btn.classList.add("seat-selected");
      btn.classList.add("seat-pulse");
      setTimeout(function () {
        btn.classList.remove("seat-pulse");
      }, 400);
    }

    updateSummary();
  }

  function updateSummary() {
    var countEl = document.getElementById("selected-count");
    var listEl = document.getElementById("selected-list");
    var totalEl = document.getElementById("selected-total");
    var submitBtn = document.getElementById("confirm-seats-btn");
    var seatIdsInput = document.getElementById("seat-ids-input");
    var summaryPanel = document.getElementById("booking-summary");

    if (countEl) countEl.textContent = selectedSeats.length;
    if (totalEl)
      totalEl.textContent = "$" + (selectedSeats.length * pricePerSeat).toFixed(2);

    if (listEl) {
      listEl.innerHTML = "";
      selectedSeats.forEach(function (s) {
        var li = document.createElement("li");
        li.className = "selected-seat-item";
        li.innerHTML =
          '<span class="seat-label-chip">' +
          s.label +
          "</span>" +
          '<span class="seat-price">$' +
          pricePerSeat.toFixed(2) +
          "</span>";
        listEl.appendChild(li);
      });
    }

    if (seatIdsInput) {
      seatIdsInput.value = selectedSeats
        .map(function (s) {
          return s.id;
        })
        .join(",");
    }

    if (submitBtn) {
      submitBtn.disabled = selectedSeats.length === 0;
    }

    if (summaryPanel) {
      if (selectedSeats.length > 0) {
        summaryPanel.classList.add("summary-visible");
      } else {
        summaryPanel.classList.remove("summary-visible");
      }
    }
  }

  window.SeatPicker = { init: init };
})();
