(function () {
  "use strict";

  var rows = 0;
  var cols = 0;
  var grid = {};
  var currentTool = "standard";

  function init(totalRows, totalCols, existingSeats) {
    rows = totalRows;
    cols = totalCols;
    grid = {};

    if (existingSeats && existingSeats.length > 0) {
      existingSeats.forEach(function (s) {
        var key = s.row + "-" + s.col;
        grid[key] = {
          row: s.row,
          col: s.col,
          label: s.label,
          type: s.type,
          active: s.active,
        };
      });
    }

    renderGrid();
    bindTools();
  }

  function renderGrid() {
    var container = document.getElementById("layout-grid");
    if (!container) return;
    container.innerHTML = "";
    container.style.setProperty("--designer-cols", cols + 1);

    // header row: column numbers
    var corner = document.createElement("div");
    corner.className = "designer-corner";
    container.appendChild(corner);
    for (var c = 1; c <= cols; c++) {
      var colHead = document.createElement("div");
      colHead.className = "designer-col-label";
      colHead.textContent = c;
      container.appendChild(colHead);
    }

    for (var r = 1; r <= rows; r++) {
      var rowLabel = document.createElement("div");
      rowLabel.className = "designer-row-label";
      rowLabel.textContent = String.fromCharCode(64 + r);
      container.appendChild(rowLabel);

      for (var c2 = 1; c2 <= cols; c2++) {
        var key = r + "-" + c2;
        var cell = document.createElement("button");
        cell.className = "designer-cell";
        cell.dataset.row = r;
        cell.dataset.col = c2;

        if (grid[key]) {
          cell.classList.add("cell-" + grid[key].type);
          cell.title =
            grid[key].label + " (" + grid[key].type + ")";
          cell.textContent = grid[key].type === "aisle" ? "" : c2;
        } else {
          cell.classList.add("cell-empty");
          cell.textContent = c2;
        }

        cell.addEventListener("click", handleCellClick);
        cell.addEventListener("contextmenu", handleRightClick);
        container.appendChild(cell);
      }
    }

    updateStats();
  }

  function handleCellClick(e) {
    var r = parseInt(e.currentTarget.dataset.row);
    var c = parseInt(e.currentTarget.dataset.col);
    var key = r + "-" + c;

    if (currentTool === "eraser") {
      delete grid[key];
    } else {
      grid[key] = {
        row: r,
        col: c,
        label: String.fromCharCode(64 + r) + c,
        type: currentTool,
        active: true,
      };
    }
    renderGrid();
  }

  function handleRightClick(e) {
    e.preventDefault();
    var r = parseInt(e.currentTarget.dataset.row);
    var c = parseInt(e.currentTarget.dataset.col);
    var key = r + "-" + c;
    delete grid[key];
    renderGrid();
  }

  function bindTools() {
    var tools = document.querySelectorAll(".tool-btn");
    tools.forEach(function (btn) {
      btn.addEventListener("click", function () {
        currentTool = btn.dataset.tool;
        tools.forEach(function (b) {
          b.classList.remove("tool-active");
        });
        btn.classList.add("tool-active");
      });
    });

    var fillAllBtn = document.getElementById("fill-all");
    if (fillAllBtn) {
      fillAllBtn.addEventListener("click", fillAll);
    }

    var clearAllBtn = document.getElementById("clear-all");
    if (clearAllBtn) {
      clearAllBtn.addEventListener("click", clearAll);
    }

    var addAisleBtn = document.getElementById("add-center-aisle");
    if (addAisleBtn) {
      addAisleBtn.addEventListener("click", addCenterAisle);
    }

    var saveBtn = document.getElementById("save-layout");
    if (saveBtn) {
      saveBtn.addEventListener("click", saveLayout);
    }
  }

  function fillAll() {
    for (var r = 1; r <= rows; r++) {
      for (var c = 1; c <= cols; c++) {
        var key = r + "-" + c;
        if (!grid[key]) {
          grid[key] = {
            row: r,
            col: c,
            label: String.fromCharCode(64 + r) + c,
            type: "standard",
            active: true,
          };
        }
      }
    }
    renderGrid();
  }

  function clearAll() {
    if (!confirm("Clear all seats?")) return;
    grid = {};
    renderGrid();
  }

  function addCenterAisle() {
    var mid = Math.ceil(cols / 2);
    for (var r = 1; r <= rows; r++) {
      var key = r + "-" + mid;
      grid[key] = {
        row: r,
        col: mid,
        label: "",
        type: "aisle",
        active: false,
      };
    }
    renderGrid();
  }

  function updateStats() {
    var total = 0;
    var vip = 0;
    var accessible = 0;
    Object.keys(grid).forEach(function (key) {
      var s = grid[key];
      if (s.type !== "aisle") {
        total++;
        if (s.type === "vip") vip++;
        if (s.type === "accessible") accessible++;
      }
    });
    var statsEl = document.getElementById("layout-stats");
    if (statsEl) {
      statsEl.innerHTML =
        "Total seats: <strong>" +
        total +
        "</strong> | VIP: <strong>" +
        vip +
        "</strong> | Accessible: <strong>" +
        accessible +
        "</strong>";
    }
  }

  function saveLayout() {
    var data = [];
    Object.keys(grid).forEach(function (key) {
      data.push(grid[key]);
    });
    var input = document.getElementById("layout-data-input");
    if (input) {
      input.value = JSON.stringify(data);
    }
    var form = document.getElementById("layout-form");
    if (form) form.submit();
  }

  window.SeatDesigner = { init: init };
})();
