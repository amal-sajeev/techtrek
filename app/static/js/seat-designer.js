(function () {
  "use strict";

  var rows = 0;
  var cols = 0;
  var stageCols = 0;
  var grid = {};
  var currentTool = "standard";
  var isDrawing = false;
  var drawMode = null;
  var lastPaintTime = 0;
  var rowGaps = {};
  var colGaps = {};

  function init(totalRows, totalCols, existingSeats, initialStageCols, initialRowGaps, initialColGaps) {
    rows = totalRows;
    cols = totalCols;
    stageCols = (initialStageCols != null && initialStageCols >= 1 && initialStageCols <= totalCols)
      ? initialStageCols
      : totalCols;
    grid = {};
    rowGaps = {};
    colGaps = {};

    if (initialRowGaps && initialRowGaps.length) {
      initialRowGaps.forEach(function (r) { rowGaps[r] = true; });
    }
    if (initialColGaps && initialColGaps.length) {
      initialColGaps.forEach(function (c) { colGaps[c] = true; });
    }

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
    bindDragPaint();
    updateFillAllLabel();
    updateGridSizeDisplay();
    updateStageWidthControl();
  }

  function rowLetter(r) {
    if (r <= 26) return String.fromCharCode(64 + r);
    return String.fromCharCode(65 + Math.floor((r - 27) / 26)) + String.fromCharCode(65 + (r - 1) % 26);
  }

  function setCell(r, c, type) {
    var key = r + "-" + c;
    if (type === "eraser" || type === null) {
      delete grid[key];
      return;
    }
    grid[key] = {
      row: r,
      col: c,
      label: type === "aisle" ? "" : rowLetter(r) + c,
      type: type,
      active: type !== "aisle",
    };
  }

  function applyToCell(r, c) {
    if (r < 1 || r > rows || c < 1 || c > cols) return;
    lastPaintTime = Date.now();
    if (drawMode === "erase") {
      setCell(r, c, null);
    } else if (drawMode === "paint" && currentTool !== "eraser") {
      setCell(r, c, currentTool);
    }
  }

  function bindDragPaint() {
    var container = document.getElementById("layout-grid");
    if (!container) return;

    container.addEventListener("mousedown", function (e) {
      var cell = e.target.closest(".designer-cell");
      if (!cell || !cell.dataset.row) return;
      e.preventDefault();
      isDrawing = true;
      drawMode = e.button === 2 ? "erase" : (currentTool === "eraser" ? "erase" : "paint");
      var r = parseInt(cell.dataset.row);
      var c = parseInt(cell.dataset.col);
      applyToCell(r, c);
      renderGrid();
    });

    document.addEventListener("mousemove", function (e) {
      if (!isDrawing) return;
      var cell = e.target.closest(".designer-cell");
      if (!cell || !cell.dataset.row) return;
      var r = parseInt(cell.dataset.row);
      var c = parseInt(cell.dataset.col);
      applyToCell(r, c);
      renderGrid();
    });

    document.addEventListener("mouseup", function () {
      isDrawing = false;
      drawMode = null;
    });
    document.addEventListener("mouseleave", function () {
      isDrawing = false;
      drawMode = null;
    });
    document.addEventListener("contextmenu", function (e) {
      if (isDrawing) e.preventDefault();
    });
  }

  function toggleRowGap(r) {
    if (r < 1 || r >= rows) return;
    if (rowGaps[r]) {
      delete rowGaps[r];
    } else {
      rowGaps[r] = true;
    }
    renderGrid();
  }

  function toggleColGap(c) {
    if (c < 1 || c >= cols) return;
    if (colGaps[c]) {
      delete colGaps[c];
    } else {
      colGaps[c] = true;
    }
    renderGrid();
  }

  function updateStageBar() {
    var bar = document.getElementById("designer-stage-bar");
    var wrapper = document.getElementById("designer-stage-wrapper");
    var gridEl = document.getElementById("layout-grid");
    if (!bar) return;
    var pct = Math.round((stageCols / cols) * 100);
    bar.style.width = pct + "%";
    bar.title = "Stage width: " + stageCols + " of " + cols + " columns (" + pct + "%)";
    if (wrapper && gridEl) {
      requestAnimationFrame(function () {
        wrapper.style.width = gridEl.offsetWidth + "px";
      });
    }
  }

  function renderGrid() {
    var container = document.getElementById("layout-grid");
    if (!container) return;
    container.innerHTML = "";

    // Build grid template columns accounting for column gaps
    var colTemplate = "auto";
    for (var ci = 1; ci <= cols; ci++) {
      colTemplate += " minmax(36px, 1fr)";
      if (ci < cols && colGaps[ci]) {
        colTemplate += " 16px";
      }
    }
    container.style.gridTemplateColumns = colTemplate;

    updateStageBar();

    // Compute grid-column for a data column (accounting for gap tracks)
    function gridCol(dataCol) {
      var gc = 1 + dataCol; // +1 for label column
      for (var g = 1; g < dataCol; g++) {
        if (colGaps[g]) gc++;
      }
      return gc;
    }

    // Total CSS grid columns
    var totalGridCols = 1 + cols;
    for (var gc2 = 1; gc2 < cols; gc2++) {
      if (colGaps[gc2]) totalGridCols++;
    }

    // Track current CSS grid row
    var gridRow = 1;

    // Header row: empty corner + column numbers
    var corner = document.createElement("div");
    corner.className = "designer-corner";
    corner.setAttribute("aria-hidden", "true");
    corner.style.gridRow = gridRow;
    corner.style.gridColumn = "1";
    container.appendChild(corner);

    for (var c = 1; c <= cols; c++) {
      var colHead = document.createElement("button");
      colHead.type = "button";
      colHead.className = "designer-col-label";
      if (colGaps[c]) colHead.classList.add("gap-active");
      colHead.textContent = c;
      colHead.dataset.col = c;
      colHead.title = "Click: fill column " + c + " · Right-click: insert/delete/clear · Shift+click: toggle gap";
      colHead.style.gridRow = gridRow;
      colHead.style.gridColumn = String(gridCol(c));
      colHead.addEventListener("click", function (ev) {
        var colNum = parseInt(ev.currentTarget.dataset.col);
        if (ev.shiftKey) {
          toggleColGap(colNum);
        } else {
          fillColumn(colNum);
        }
      });
      colHead.addEventListener("contextmenu", function (ev) {
        ev.preventDefault();
        var cn = parseInt(ev.currentTarget.dataset.col);
        var items = [
          { label: "Insert column before " + cn, action: function () { insertColAt(cn); } },
          { label: "Insert column after " + cn, action: function () { insertColAt(cn + 1); } },
          { divider: true }
        ];
        if (cn > 1) {
          items.push({ label: (colGaps[cn - 1] ? "Remove" : "Add") + " gap before " + cn, action: function () { toggleColGap(cn - 1); } });
        }
        if (cn < cols) {
          items.push({ label: (colGaps[cn] ? "Remove" : "Add") + " gap after " + cn, action: function () { toggleColGap(cn); } });
        }
        items.push({ divider: true });
        items.push({ label: "Clear column " + cn, action: function () { clearColumn(cn); } });
        items.push({ label: "Delete column " + cn, danger: true, action: function () { deleteColAt(cn); } });
        showContextMenu(ev.clientX, ev.clientY, items);
      });
      container.appendChild(colHead);

      // Column gap indicator in header row
      if (c < cols && colGaps[c]) {
        var colGapEl = document.createElement("div");
        colGapEl.className = "designer-col-gap-indicator";
        colGapEl.style.gridRow = gridRow;
        colGapEl.style.gridColumn = String(gridCol(c) + 1);
        colGapEl.title = "Column gap after col " + c + " — Shift+click column header to remove";
        container.appendChild(colGapEl);
      }
    }

    gridRow++;

    // Data rows with optional row gap handles between them
    for (var r = 1; r <= rows; r++) {
      var rowLabel = document.createElement("button");
      rowLabel.type = "button";
      rowLabel.className = "designer-row-label";
      if (rowGaps[r]) rowLabel.classList.add("gap-active");
      rowLabel.textContent = rowLetter(r);
      rowLabel.dataset.row = r;
      rowLabel.title = "Click: fill row " + rowLabel.textContent + " · Right-click: insert/delete/clear · Shift+click: toggle gap";
      rowLabel.style.gridRow = gridRow;
      rowLabel.style.gridColumn = "1";
      rowLabel.addEventListener("click", function (ev) {
        var rowNum = parseInt(ev.currentTarget.dataset.row);
        if (ev.shiftKey) {
          toggleRowGap(rowNum);
        } else {
          fillRow(rowNum);
        }
      });
      rowLabel.addEventListener("contextmenu", function (ev) {
        ev.preventDefault();
        var rn = parseInt(ev.currentTarget.dataset.row);
        var letter = rowLetter(rn);
        var items = [
          { label: "Insert row above " + letter, action: function () { insertRowAt(rn); } },
          { label: "Insert row below " + letter, action: function () { insertRowAt(rn + 1); } },
          { divider: true }
        ];
        if (rn > 1) {
          items.push({ label: (rowGaps[rn - 1] ? "Remove" : "Add") + " gap above " + letter, action: function () { toggleRowGap(rn - 1); } });
        }
        if (rn < rows) {
          items.push({ label: (rowGaps[rn] ? "Remove" : "Add") + " gap below " + letter, action: function () { toggleRowGap(rn); } });
        }
        items.push({ divider: true });
        items.push({ label: "Clear row " + letter, action: function () { clearRow(rn); } });
        items.push({ label: "Delete row " + letter, danger: true, action: function () { deleteRowAt(rn); } });
        showContextMenu(ev.clientX, ev.clientY, items);
      });
      container.appendChild(rowLabel);

      for (var c2 = 1; c2 <= cols; c2++) {
        var key = r + "-" + c2;
        var cell = document.createElement("button");
        cell.type = "button";
        cell.className = "designer-cell";
        cell.dataset.row = r;
        cell.dataset.col = c2;
        cell.style.gridRow = gridRow;
        cell.style.gridColumn = String(gridCol(c2));

        if (grid[key]) {
          cell.classList.add("cell-" + grid[key].type);
          cell.title = grid[key].label ? grid[key].label + " — " + grid[key].type : grid[key].type;
          cell.textContent = grid[key].type === "aisle" ? "—" : grid[key].label;
        } else {
          cell.classList.add("cell-empty");
          cell.title = "Row " + rowLetter(r) + ", seat " + c2 + " — click or drag to add";
          cell.textContent = "+";
        }

        cell.addEventListener("click", handleCellClick);
        cell.addEventListener("contextmenu", handleRightClick);
        container.appendChild(cell);

        // Column gap spacer in data rows
        if (c2 < cols && colGaps[c2]) {
          var colSpacer = document.createElement("div");
          colSpacer.className = "designer-col-gap-spacer";
          colSpacer.style.gridRow = gridRow;
          colSpacer.style.gridColumn = String(gridCol(c2) + 1);
          container.appendChild(colSpacer);
        }
      }

      gridRow++;

      // Row gap handle after this row (if not last row)
      if (r < rows) {
        var gapHandle = document.createElement("button");
        gapHandle.type = "button";
        gapHandle.className = "designer-row-gap-handle";
        if (rowGaps[r]) gapHandle.classList.add("gap-active");
        gapHandle.dataset.gapAfterRow = r;
        gapHandle.style.gridRow = gridRow;
        gapHandle.style.gridColumn = "1 / " + (totalGridCols + 1);
        gapHandle.title = rowGaps[r]
          ? "Gap after row " + rowLetter(r) + " — click to remove"
          : "Click to add gap after row " + rowLetter(r);
        gapHandle.addEventListener("click", function (ev) {
          toggleRowGap(parseInt(ev.currentTarget.dataset.gapAfterRow));
        });
        container.appendChild(gapHandle);
        gridRow++;
      }
    }

    updateStats();
    updateGridSizeDisplay();
  }

  function handleCellClick(e) {
    if (isDrawing) return;
    if (Date.now() - lastPaintTime < 120) return;
    var r = parseInt(e.currentTarget.dataset.row);
    var c = parseInt(e.currentTarget.dataset.col);
    if (currentTool === "eraser") {
      setCell(r, c, null);
    } else {
      setCell(r, c, currentTool);
    }
    renderGrid();
  }

  function handleRightClick(e) {
    e.preventDefault();
    if (isDrawing) return;
    var r = parseInt(e.currentTarget.dataset.row);
    var c = parseInt(e.currentTarget.dataset.col);
    setCell(r, c, null);
    renderGrid();
  }

  function fillRow(rowNum) {
    if (currentTool === "eraser") return;
    for (var c = 1; c <= cols; c++) {
      setCell(rowNum, c, currentTool);
    }
    renderGrid();
  }

  function fillColumn(colNum) {
    if (currentTool === "eraser") return;
    for (var r = 1; r <= rows; r++) {
      setCell(r, colNum, currentTool);
    }
    renderGrid();
  }

  function clearRow(rowNum) {
    for (var c = 1; c <= cols; c++) {
      setCell(rowNum, c, null);
    }
    renderGrid();
  }

  function clearColumn(colNum) {
    for (var r = 1; r <= rows; r++) {
      setCell(r, colNum, null);
    }
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
        updateFillAllLabel();
      });
    });

    var fillAllBtn = document.getElementById("fill-all");
    if (fillAllBtn) fillAllBtn.addEventListener("click", fillAll);

    var clearAllBtn = document.getElementById("clear-all");
    if (clearAllBtn) clearAllBtn.addEventListener("click", clearAll);

    var addAisleBtn = document.getElementById("add-center-aisle");
    if (addAisleBtn) addAisleBtn.addEventListener("click", addCenterAisle);

    var addRowBtn = document.getElementById("add-row");
    if (addRowBtn) addRowBtn.addEventListener("click", addRow);
    var addColBtn = document.getElementById("add-column");
    if (addColBtn) addColBtn.addEventListener("click", addColumn);
    var removeRowBtn = document.getElementById("remove-row");
    if (removeRowBtn) removeRowBtn.addEventListener("click", removeRow);
    var removeColBtn = document.getElementById("remove-column");
    if (removeColBtn) removeColBtn.addEventListener("click", removeColumn);

    var stageWidthInput = document.getElementById("stage-width-input");
    if (stageWidthInput) {
      stageWidthInput.addEventListener("change", function () { setStageCols(stageWidthInput.value); });
      stageWidthInput.addEventListener("input", function () { setStageCols(stageWidthInput.value); });
    }
    var stageWidthDown = document.getElementById("stage-width-down");
    if (stageWidthDown) stageWidthDown.addEventListener("click", function () { setStageCols(stageCols - 1); });
    var stageWidthUp = document.getElementById("stage-width-up");
    if (stageWidthUp) stageWidthUp.addEventListener("click", function () { setStageCols(stageCols + 1); });

    var saveBtn = document.getElementById("save-layout");
    if (saveBtn) saveBtn.addEventListener("click", saveLayout);
  }

  function updateFillAllLabel() {
    var btn = document.getElementById("fill-all");
    if (!btn) return;
    if (currentTool === "eraser") {
      btn.textContent = "Fill all (select a type first)";
      btn.disabled = true;
    } else {
      btn.textContent = "Fill all with " + (currentTool.charAt(0).toUpperCase() + currentTool.slice(1));
      btn.disabled = false;
    }
  }

  function fillAll() {
    if (currentTool === "eraser") return;
    for (var r = 1; r <= rows; r++) {
      for (var c = 1; c <= cols; c++) {
        setCell(r, c, currentTool);
      }
    }
    renderGrid();
  }

  function clearAll() {
    if (!confirm("Clear all seats, aisles, and gaps?")) return;
    grid = {};
    rowGaps = {};
    colGaps = {};
    renderGrid();
  }

  function addCenterAisle() {
    var mid = Math.ceil(cols / 2);
    for (var r = 1; r <= rows; r++) {
      setCell(r, mid, "aisle");
    }
    renderGrid();
  }

  function addRow() {
    rows += 1;
    updateGridSizeDisplay();
    renderGrid();
  }

  function addColumn() {
    cols += 1;
    updateGridSizeDisplay();
    renderGrid();
  }

  function removeRow() {
    if (rows <= 1) return;
    var hasSeats = false;
    for (var c = 1; c <= cols; c++) {
      if (grid[rows + "-" + c]) { hasSeats = true; break; }
    }
    if (hasSeats && !confirm("Row " + rowLetter(rows) + " has seats. Remove it anyway?")) return;
    for (var c = 1; c <= cols; c++) {
      setCell(rows, c, null);
    }
    delete rowGaps[rows];
    delete rowGaps[rows - 1];
    rows -= 1;
    updateGridSizeDisplay();
    renderGrid();
  }

  function removeColumn() {
    if (cols <= 1) return;
    var hasSeats = false;
    for (var r = 1; r <= rows; r++) {
      if (grid[r + "-" + cols]) { hasSeats = true; break; }
    }
    if (hasSeats && !confirm("Column " + cols + " has seats. Remove it anyway?")) return;
    for (var r = 1; r <= rows; r++) {
      setCell(r, cols, null);
    }
    delete colGaps[cols];
    delete colGaps[cols - 1];
    cols -= 1;
    if (stageCols > cols) stageCols = cols;
    updateGridSizeDisplay();
    updateStageWidthControl();
    renderGrid();
  }

  /* ---- Insert / delete rows & columns at arbitrary positions ---- */

  function rebuildEntry(s, newRow, newCol) {
    return {
      row: newRow,
      col: newCol,
      label: s.type === "aisle" ? "" : rowLetter(newRow) + newCol,
      type: s.type,
      active: s.type !== "aisle"
    };
  }

  function insertRowAt(pos) {
    var newGrid = {};
    Object.keys(grid).forEach(function (key) {
      var s = grid[key];
      if (s.row >= pos) {
        var nr = s.row + 1;
        newGrid[nr + "-" + s.col] = rebuildEntry(s, nr, s.col);
      } else {
        newGrid[key] = s;
      }
    });
    grid = newGrid;
    var newGaps = {};
    Object.keys(rowGaps).forEach(function (k) {
      var g = parseInt(k, 10);
      newGaps[g >= pos ? g + 1 : g] = true;
    });
    rowGaps = newGaps;
    rows += 1;
    updateGridSizeDisplay();
    renderGrid();
  }

  function deleteRowAt(pos) {
    if (rows <= 1) return;
    var hasSeats = false;
    for (var c = 1; c <= cols; c++) {
      if (grid[pos + "-" + c]) { hasSeats = true; break; }
    }
    if (hasSeats && !confirm("Row " + rowLetter(pos) + " has seats. Delete it?")) return;
    var newGrid = {};
    Object.keys(grid).forEach(function (key) {
      var s = grid[key];
      if (s.row === pos) return;
      if (s.row > pos) {
        var nr = s.row - 1;
        newGrid[nr + "-" + s.col] = rebuildEntry(s, nr, s.col);
      } else {
        newGrid[key] = s;
      }
    });
    grid = newGrid;
    var newGaps = {};
    Object.keys(rowGaps).forEach(function (k) {
      var g = parseInt(k, 10);
      if (g === pos || g === rows) return;
      newGaps[g > pos ? g - 1 : g] = true;
    });
    rowGaps = newGaps;
    rows -= 1;
    updateGridSizeDisplay();
    renderGrid();
  }

  function insertColAt(pos) {
    var newGrid = {};
    Object.keys(grid).forEach(function (key) {
      var s = grid[key];
      if (s.col >= pos) {
        var nc = s.col + 1;
        newGrid[s.row + "-" + nc] = rebuildEntry(s, s.row, nc);
      } else {
        newGrid[key] = s;
      }
    });
    grid = newGrid;
    var newGaps = {};
    Object.keys(colGaps).forEach(function (k) {
      var g = parseInt(k, 10);
      newGaps[g >= pos ? g + 1 : g] = true;
    });
    colGaps = newGaps;
    cols += 1;
    if (stageCols >= pos) stageCols += 1;
    updateGridSizeDisplay();
    updateStageWidthControl();
    renderGrid();
  }

  function deleteColAt(pos) {
    if (cols <= 1) return;
    var hasSeats = false;
    for (var r = 1; r <= rows; r++) {
      if (grid[r + "-" + pos]) { hasSeats = true; break; }
    }
    if (hasSeats && !confirm("Column " + pos + " has seats. Delete it?")) return;
    var newGrid = {};
    Object.keys(grid).forEach(function (key) {
      var s = grid[key];
      if (s.col === pos) return;
      if (s.col > pos) {
        var nc = s.col - 1;
        newGrid[s.row + "-" + nc] = rebuildEntry(s, s.row, nc);
      } else {
        newGrid[key] = s;
      }
    });
    grid = newGrid;
    var newGaps = {};
    Object.keys(colGaps).forEach(function (k) {
      var g = parseInt(k, 10);
      if (g === pos || g === cols) return;
      newGaps[g > pos ? g - 1 : g] = true;
    });
    colGaps = newGaps;
    cols -= 1;
    if (stageCols > cols) stageCols = cols;
    updateGridSizeDisplay();
    updateStageWidthControl();
    renderGrid();
  }

  /* ---- Context menu for row / column labels ---- */

  var ctxMenu = null;

  function closeContextMenu() {
    if (ctxMenu && ctxMenu.parentNode) ctxMenu.parentNode.removeChild(ctxMenu);
    ctxMenu = null;
  }

  function showContextMenu(x, y, items) {
    closeContextMenu();
    ctxMenu = document.createElement("div");
    ctxMenu.className = "designer-ctx-menu";
    items.forEach(function (item) {
      if (item.divider) {
        var hr = document.createElement("div");
        hr.className = "designer-ctx-divider";
        ctxMenu.appendChild(hr);
        return;
      }
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "designer-ctx-item";
      if (item.danger) btn.classList.add("designer-ctx-danger");
      btn.textContent = item.label;
      btn.addEventListener("click", function () {
        closeContextMenu();
        item.action();
      });
      ctxMenu.appendChild(btn);
    });
    document.body.appendChild(ctxMenu);

    var rect = ctxMenu.getBoundingClientRect();
    var vw = window.innerWidth;
    var vh = window.innerHeight;
    if (x + rect.width > vw) x = vw - rect.width - 8;
    if (y + rect.height > vh) y = vh - rect.height - 8;
    ctxMenu.style.left = Math.max(4, x) + "px";
    ctxMenu.style.top = Math.max(4, y) + "px";
  }

  document.addEventListener("click", function (e) {
    if (ctxMenu && !ctxMenu.contains(e.target)) closeContextMenu();
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closeContextMenu();
  });

  function setStageCols(n) {
    stageCols = Math.max(1, Math.min(cols, parseInt(n, 10) || cols));
    updateStageWidthControl();
    updateStageBar();
  }

  function updateStageWidthControl() {
    var input = document.getElementById("stage-width-input");
    if (input) {
      input.value = stageCols;
      input.min = 1;
      input.max = cols;
    }
  }

  function updateGridSizeDisplay() {
    var el = document.getElementById("layout-grid-size");
    if (el) el.textContent = rows + " rows \u00d7 " + cols + " columns";
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
    var gapCount = Object.keys(rowGaps).length + Object.keys(colGaps).length;
    var statsEl = document.getElementById("layout-stats");
    if (statsEl) {
      statsEl.innerHTML =
        "Total seats: <strong>" + total +
        "</strong> | VIP: <strong>" + vip +
        "</strong> | Accessible: <strong>" + accessible +
        "</strong> | Gaps: <strong>" + gapCount + "</strong>";
    }
  }

  function gapKeysToArray(obj) {
    return Object.keys(obj).map(function (k) { return parseInt(k, 10); }).sort(function (a, b) { return a - b; });
  }

  function saveLayout() {
    var data = [];
    Object.keys(grid).forEach(function (key) {
      data.push(grid[key]);
    });
    var input = document.getElementById("layout-data-input");
    if (input) input.value = JSON.stringify(data);

    var rowsInput = document.getElementById("layout-total-rows");
    var colsInput = document.getElementById("layout-total-cols");
    if (rowsInput) rowsInput.value = rows;
    if (colsInput) colsInput.value = cols;

    var stageColsInput = document.getElementById("layout-stage-cols");
    if (stageColsInput) stageColsInput.value = stageCols;

    var rowGapsInput = document.getElementById("layout-row-gaps");
    var colGapsInput = document.getElementById("layout-col-gaps");
    if (rowGapsInput) rowGapsInput.value = JSON.stringify(gapKeysToArray(rowGaps));
    if (colGapsInput) colGapsInput.value = JSON.stringify(gapKeysToArray(colGaps));

    var form = document.getElementById("layout-form");
    if (form) form.submit();
  }

  window.SeatDesigner = { init: init };
})();
