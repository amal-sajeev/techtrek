(function () {
  "use strict";

  var rows = 0;
  var cols = 0;
  var stageCols = 0;
  var stageOffset = 0;
  var stageLabel = "Stage";
  var grid = {};
  var entryExitMarkers = [];
  var currentTool = "standard";
  var selectedCustomType = null;
  var customTypes = {};
  var isDrawing = false;
  var drawMode = null;
  var lastPaintTime = 0;
  var rowGaps = {};
  var colGaps = {};

  function init(totalRows, totalCols, existingSeats, initialStageCols, initialRowGaps, initialColGaps, initialStageOffset, initialStageLabel, initialEntryExit, initialCustomTypes) {
    rows = totalRows;
    cols = totalCols;
    stageCols = (initialStageCols != null && initialStageCols >= 1 && initialStageCols <= totalCols)
      ? initialStageCols
      : totalCols;
    stageOffset = initialStageOffset || 0;
    stageLabel = initialStageLabel || "Stage";
    grid = {};
    rowGaps = {};
    colGaps = {};
    entryExitMarkers = [];
    customTypes = {};
    selectedCustomType = null;

    if (initialCustomTypes && initialCustomTypes.length) {
      initialCustomTypes.forEach(function (ct) {
        customTypes["custom_" + ct.id] = ct;
      });
      populateCustomTypeDropdown(initialCustomTypes);
      renderCustomLegend(initialCustomTypes);
    }

    if (initialRowGaps && initialRowGaps.length) {
      initialRowGaps.forEach(function (r) { rowGaps[r] = true; });
    }
    if (initialColGaps && initialColGaps.length) {
      initialColGaps.forEach(function (c) { colGaps[c] = true; });
    }

    if (initialEntryExit && initialEntryExit.length) {
      entryExitMarkers = initialEntryExit.slice();
      migrateLegacyMarkers();
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
    bindMarkerPanel();
    bindPreview();
    updateFillAllLabel();
    updateGridSizeDisplay();
    updateStageWidthControl();
    initStageDrag();
    updateStageLabelDisplay();
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

  var SEAT_TOOLS = { standard: 1, vip: 1, accessible: 1, aisle: 1, eraser: 1, custom: 1 };

  function isCustomType(type) {
    return type && type.indexOf("custom_") === 0;
  }

  function getEffectiveTool() {
    if (currentTool === "custom" && selectedCustomType) {
      return "custom_" + selectedCustomType;
    }
    return currentTool;
  }

  function populateCustomTypeDropdown(types) {
    var sel = document.getElementById("custom-type-select");
    if (!sel) return;
    while (sel.options.length > 1) sel.remove(1);
    types.forEach(function (ct) {
      var opt = document.createElement("option");
      opt.value = ct.id;
      opt.textContent = ct.name;
      opt.style.color = ct.colour;
      sel.appendChild(opt);
    });
  }

  function renderCustomLegend(types) {
    var container = document.getElementById("custom-legend-items");
    if (!container) return;
    container.innerHTML = "";
    types.forEach(function (ct) {
      var item = document.createElement("span");
      item.className = "designer-legend-item";
      var swatch = document.createElement("span");
      swatch.className = "designer-legend-swatch";
      swatch.style.background = ct.colour;
      item.appendChild(swatch);
      item.appendChild(document.createTextNode(" " + ct.name));
      container.appendChild(item);
    });
  }

  function applyToCell(r, c) {
    if (r < 1 || r > rows || c < 1 || c > cols) return;
    var tool = getEffectiveTool();
    if (!SEAT_TOOLS[currentTool] && !isCustomType(tool)) return;
    lastPaintTime = Date.now();
    if (drawMode === "erase") {
      setCell(r, c, null);
    } else if (drawMode === "paint" && currentTool !== "eraser") {
      if (currentTool === "custom" && !selectedCustomType) return;
      setCell(r, c, tool);
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

  function getDataArea() {
    var gridEl = document.getElementById("layout-grid");
    if (!gridEl) return null;
    var colLabels = gridEl.querySelectorAll(".designer-col-label");
    if (!colLabels.length) return null;
    var gridRect = gridEl.getBoundingClientRect();
    var first = colLabels[0].getBoundingClientRect();
    var last = colLabels[colLabels.length - 1].getBoundingClientRect();
    return {
      left: first.left - gridRect.left,
      width: last.right - first.left,
      gridWidth: gridEl.offsetWidth
    };
  }

  function updateStageBar() {
    var bar = document.getElementById("designer-stage-bar");
    var wrapper = document.getElementById("designer-stage-wrapper");
    var gridEl = document.getElementById("layout-grid");
    if (!bar || !wrapper || !gridEl) return;
    bar.title = "Stage width: " + stageCols + " of " + cols + " columns · Drag to reposition";
    var textEl = bar.querySelector(".designer-stage-bar-text");
    if (textEl) textEl.textContent = stageLabel.toUpperCase();
    requestAnimationFrame(function () {
      wrapper.style.width = gridEl.offsetWidth + "px";
      var area = getDataArea();
      if (!area) return;
      var colWidth = area.width / cols;
      bar.style.width = Math.round(stageCols * colWidth) + "px";
      bar.style.marginLeft = Math.round(area.left + stageOffset * colWidth) + "px";
    });
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
          var cellType = grid[key].type;
          if (isCustomType(cellType) && customTypes[cellType]) {
            cell.classList.add("cell-custom");
            cell.style.backgroundColor = customTypes[cellType].colour;
            cell.title = grid[key].label ? grid[key].label + " — " + customTypes[cellType].name : customTypes[cellType].name;
          } else {
            cell.classList.add("cell-" + cellType);
            cell.title = grid[key].label ? grid[key].label + " — " + cellType : cellType;
          }
          cell.textContent = cellType === "aisle" ? "—" : grid[key].label;
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
    renderMarkerPanel();
    renderDraggableMarkers();
  }

  function handleCellClick(e) {
    if (isDrawing) return;
    if (Date.now() - lastPaintTime < 120) return;
    var tool = getEffectiveTool();
    if (!SEAT_TOOLS[currentTool] && !isCustomType(tool)) return;
    var r = parseInt(e.currentTarget.dataset.row);
    var c = parseInt(e.currentTarget.dataset.col);
    if (currentTool === "eraser") {
      setCell(r, c, null);
    } else {
      if (currentTool === "custom" && !selectedCustomType) return;
      setCell(r, c, tool);
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
    var tool = getEffectiveTool();
    if (currentTool === "custom" && !selectedCustomType) return;
    for (var c = 1; c <= cols; c++) {
      setCell(rowNum, c, tool);
    }
    renderGrid();
  }

  function fillColumn(colNum) {
    if (currentTool === "eraser") return;
    var tool = getEffectiveTool();
    if (currentTool === "custom" && !selectedCustomType) return;
    for (var r = 1; r <= rows; r++) {
      setCell(r, colNum, tool);
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
    var customSelect = document.getElementById("custom-type-select");
    tools.forEach(function (btn) {
      btn.addEventListener("click", function () {
        currentTool = btn.dataset.tool;
        tools.forEach(function (b) {
          b.classList.remove("tool-active");
        });
        btn.classList.add("tool-active");
        if (customSelect) {
          customSelect.style.display = currentTool === "custom" ? "" : "none";
        }
        updateFillAllLabel();
      });
    });
    if (customSelect) {
      customSelect.addEventListener("change", function () {
        selectedCustomType = customSelect.value || null;
        updateFillAllLabel();
        var swatchEl = document.querySelector("#custom-tool-btn .tool-swatch");
        if (swatchEl && selectedCustomType && customTypes["custom_" + selectedCustomType]) {
          swatchEl.style.background = customTypes["custom_" + selectedCustomType].colour;
        }
      });
    }

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
    } else if (currentTool === "custom") {
      if (selectedCustomType && customTypes["custom_" + selectedCustomType]) {
        btn.textContent = "Fill all with " + customTypes["custom_" + selectedCustomType].name;
        btn.disabled = false;
      } else {
        btn.textContent = "Fill all (select a custom type)";
        btn.disabled = true;
      }
    } else {
      btn.textContent = "Fill all with " + (currentTool.charAt(0).toUpperCase() + currentTool.slice(1));
      btn.disabled = false;
    }
  }

  function fillAll() {
    if (currentTool === "eraser") return;
    var tool = getEffectiveTool();
    if (currentTool === "custom" && !selectedCustomType) return;
    for (var r = 1; r <= rows; r++) {
      for (var c = 1; c <= cols; c++) {
        setCell(r, c, tool);
      }
    }
    renderGrid();
  }

  function clearAll() {
    openConfirm("Clear all seats, aisles, and gaps?", function() {
      grid = {};
      rowGaps = {};
      colGaps = {};
      renderGrid();
    }, { confirmLabel: "Clear All" });
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
    if (hasSeats) {
      openConfirm("Row " + rowLetter(rows) + " has seats. Remove it anyway?", function() {
        doRemoveRow();
      }, { confirmLabel: "Remove" });
      return;
    }
    doRemoveRow();
    function doRemoveRow() {
      for (var c2 = 1; c2 <= cols; c2++) {
        setCell(rows, c2, null);
      }
      delete rowGaps[rows];
      delete rowGaps[rows - 1];
      rows -= 1;
      updateGridSizeDisplay();
      renderGrid();
    }
  }

  function removeColumn() {
    if (cols <= 1) return;
    var hasSeats = false;
    for (var r = 1; r <= rows; r++) {
      if (grid[r + "-" + cols]) { hasSeats = true; break; }
    }
    if (hasSeats) {
      openConfirm("Column " + cols + " has seats. Remove it anyway?", function() {
        doRemoveCol();
      }, { confirmLabel: "Remove" });
      return;
    }
    doRemoveCol();
    function doRemoveCol() {
      for (var r2 = 1; r2 <= rows; r2++) {
        setCell(r2, cols, null);
      }
      delete colGaps[cols];
      delete colGaps[cols - 1];
      cols -= 1;
      if (stageCols > cols) stageCols = cols;
      updateGridSizeDisplay();
      updateStageWidthControl();
      renderGrid();
    }
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
    if (hasSeats) {
      openConfirm("Row " + rowLetter(pos) + " has seats. Delete it?", function() {
        doDeleteRow();
      }, { confirmLabel: "Delete" });
      return;
    }
    doDeleteRow();
    function doDeleteRow() {
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
    if (hasSeats) {
      openConfirm("Column " + pos + " has seats. Delete it?", function() {
        doDeleteCol();
      }, { confirmLabel: "Delete" });
      return;
    }
    doDeleteCol();
    function doDeleteCol() {
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
    var customCounts = {};
    Object.keys(grid).forEach(function (key) {
      var s = grid[key];
      if (s.type !== "aisle") {
        total++;
        if (s.type === "vip") vip++;
        else if (s.type === "accessible") accessible++;
        else if (isCustomType(s.type) && customTypes[s.type]) {
          var name = customTypes[s.type].name;
          customCounts[name] = (customCounts[name] || 0) + 1;
        }
      }
    });
    var gapCount = Object.keys(rowGaps).length + Object.keys(colGaps).length;
    var statsEl = document.getElementById("layout-stats");
    if (statsEl) {
      var html =
        "Total seats: <strong>" + total +
        "</strong> | VIP: <strong>" + vip +
        "</strong> | Accessible: <strong>" + accessible + "</strong>";
      Object.keys(customCounts).forEach(function (name) {
        html += " | " + name + ": <strong>" + customCounts[name] + "</strong>";
      });
      html += " | Gaps: <strong>" + gapCount + "</strong>";
      statsEl.innerHTML = html;
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

    var stageOffsetInput = document.getElementById("layout-stage-offset");
    if (stageOffsetInput) stageOffsetInput.value = stageOffset;

    var stageLabelInput = document.getElementById("layout-stage-label");
    if (stageLabelInput) stageLabelInput.value = stageLabel;

    var entryExitInput = document.getElementById("layout-entry-exit");
    if (entryExitInput) entryExitInput.value = JSON.stringify(entryExitMarkers);

    var rowGapsInput = document.getElementById("layout-row-gaps");
    var colGapsInput = document.getElementById("layout-col-gaps");
    if (rowGapsInput) rowGapsInput.value = JSON.stringify(gapKeysToArray(rowGaps));
    if (colGapsInput) colGapsInput.value = JSON.stringify(gapKeysToArray(colGaps));

    var form = document.getElementById("layout-form");
    if (form) form.submit();
  }

  /* ---- Entry/Exit markers (freely draggable) ---- */

  function nextMarkerLabel(type) {
    var prefix = type.charAt(0).toUpperCase() + type.slice(1);
    var existing = entryExitMarkers.filter(function (m) { return m.type === type; });
    var letter = String.fromCharCode(65 + existing.length);
    return prefix + " " + letter;
  }

  function migrateLegacyMarkers() {
    entryExitMarkers.forEach(function (m) {
      if (typeof m.x === "number" && typeof m.y === "number") return;
      if (m.side === "top")         { m.x = ((m.position - 0.5) / cols) * 100; m.y = 0; }
      else if (m.side === "bottom") { m.x = ((m.position - 0.5) / cols) * 100; m.y = 100; }
      else if (m.side === "left")   { m.x = 0; m.y = ((m.position - 0.5) / rows) * 100; }
      else if (m.side === "right")  { m.x = 100; m.y = ((m.position - 0.5) / rows) * 100; }
      else                          { m.x = 50; m.y = 0; }
      delete m.side;
      delete m.position;
    });
  }

  function addMarker(type) {
    var count = entryExitMarkers.length;
    var defaultX = 10 + (count % 5) * 20;
    var defaultY = type === "entry" ? 0 : 100;
    entryExitMarkers.push({
      type: type,
      label: nextMarkerLabel(type),
      x: defaultX,
      y: defaultY
    });
    renderMarkerPanel();
    renderDraggableMarkers();
  }

  function removeMarker(index) {
    entryExitMarkers.splice(index, 1);
    renderMarkerPanel();
    renderDraggableMarkers();
  }

  function renderMarkerPanel() {
    var listEl = document.getElementById("marker-list");
    if (!listEl) return;
    listEl.innerHTML = "";
    if (entryExitMarkers.length === 0) {
      var empty = document.createElement("p");
      empty.className = "marker-empty-msg";
      empty.textContent = "No markers placed yet. Click \"+ Add Marker\" to create one.";
      listEl.appendChild(empty);
      return;
    }
    entryExitMarkers.forEach(function (m, i) {
      var row = document.createElement("div");
      row.className = "marker-list-item";

      var icon = document.createElement("span");
      icon.className = "marker-type-badge marker-badge-" + m.type;
      icon.textContent = m.type === "entry" ? "\u2B95" : "\u2934";
      row.appendChild(icon);

      var labelInput = document.createElement("input");
      labelInput.type = "text";
      labelInput.className = "form-input marker-label-input";
      labelInput.value = m.label;
      labelInput.addEventListener("input", function () {
        var val = labelInput.value.trim();
        if (val) {
          entryExitMarkers[i].label = val;
          var marker = document.querySelector('.draggable-marker[data-marker-idx="' + i + '"]');
          if (marker) marker.textContent = val;
        }
      });
      row.appendChild(labelInput);

      var removeBtn = document.createElement("button");
      removeBtn.type = "button";
      removeBtn.className = "btn btn-sm btn-danger marker-remove-btn";
      removeBtn.textContent = "Remove";
      removeBtn.addEventListener("click", function () { removeMarker(i); });
      row.appendChild(removeBtn);

      listEl.appendChild(row);
    });
  }

  function renderDraggableMarkers() {
    var anchor = document.getElementById("marker-anchor");
    if (!anchor) return;
    anchor.querySelectorAll(".draggable-marker").forEach(function (el) { el.remove(); });

    entryExitMarkers.forEach(function (m, idx) {
      var el = document.createElement("div");
      el.className = "draggable-marker draggable-marker-" + m.type;
      el.textContent = m.label;
      el.title = m.label + " \u2014 drag to reposition";
      el.dataset.markerIdx = idx;
      el.style.left = m.x + "%";
      el.style.top = m.y + "%";
      initMarkerDrag(el, idx, anchor);
      anchor.appendChild(el);
    });

    adjustContainerForMarkers();
  }

  function initMarkerDrag(el, idx, anchor) {
    var dragging = false;
    var startMouseX, startMouseY, startElX, startElY;

    el.addEventListener("mousedown", function (e) {
      e.preventDefault();
      e.stopPropagation();
      dragging = true;
      startMouseX = e.clientX;
      startMouseY = e.clientY;
      startElX = entryExitMarkers[idx].x;
      startElY = entryExitMarkers[idx].y;
      el.classList.add("marker-dragging");
    });

    document.addEventListener("mousemove", function (e) {
      if (!dragging) return;
      var rect = anchor.getBoundingClientRect();
      var dx = e.clientX - startMouseX;
      var dy = e.clientY - startMouseY;
      var pctX = startElX + (dx / rect.width) * 100;
      var pctY = startElY + (dy / rect.height) * 100;
      pctX = Math.max(-10, Math.min(110, pctX));
      pctY = Math.max(-10, Math.min(110, pctY));
      el.style.left = pctX + "%";
      el.style.top = pctY + "%";
    });

    document.addEventListener("mouseup", function () {
      if (!dragging) return;
      dragging = false;
      el.classList.remove("marker-dragging");
      var pctX = parseFloat(el.style.left);
      var pctY = parseFloat(el.style.top);
      entryExitMarkers[idx].x = Math.round(pctX * 10) / 10;
      entryExitMarkers[idx].y = Math.round(pctY * 10) / 10;
      adjustContainerForMarkers();
    });
  }

  function adjustContainerForMarkers() {
    var container = document.getElementById("designer-container");
    var anchor = document.getElementById("marker-anchor");
    if (!container || !anchor) return;

    container.style.paddingTop = "";
    container.style.paddingBottom = "";
    container.style.paddingLeft = "";
    container.style.paddingRight = "";

    requestAnimationFrame(function () {
      var containerRect = container.getBoundingClientRect();
      var markers = anchor.querySelectorAll(".draggable-marker");
      var extraTop = 0, extraBottom = 0, extraLeft = 0, extraRight = 0;

      markers.forEach(function (m) {
        var r = m.getBoundingClientRect();
        var ot = containerRect.top - r.top;
        if (ot > 0) extraTop = Math.max(extraTop, ot);
        var ob = r.bottom - containerRect.bottom;
        if (ob > 0) extraBottom = Math.max(extraBottom, ob);
        var ol = containerRect.left - r.left;
        if (ol > 0) extraLeft = Math.max(extraLeft, ol);
        var or2 = r.right - containerRect.right;
        if (or2 > 0) extraRight = Math.max(extraRight, or2);
      });

      var cs = getComputedStyle(container);
      var padT = parseFloat(cs.paddingTop);
      var padB = parseFloat(cs.paddingBottom);
      var padL = parseFloat(cs.paddingLeft);
      var padR = parseFloat(cs.paddingRight);

      if (extraTop > 0) container.style.paddingTop = (padT + extraTop + 8) + "px";
      if (extraBottom > 0) container.style.paddingBottom = (padB + extraBottom + 8) + "px";
      if (extraLeft > 0) container.style.paddingLeft = (padL + extraLeft + 8) + "px";
      if (extraRight > 0) container.style.paddingRight = (padR + extraRight + 8) + "px";
    });
  }

  function bindMarkerPanel() {
    var addBtn = document.getElementById("add-marker-btn");
    if (addBtn) {
      addBtn.addEventListener("click", function () {
        var type = document.getElementById("marker-type-select").value;
        addMarker(type);
      });
    }
  }

  /* ---- Draggable stage ---- */

  function initStageDrag() {
    var bar = document.getElementById("designer-stage-bar");
    if (!bar) return;
    bar.style.cursor = "grab";

    var dragging = false;
    var startX = 0;
    var startOffset = 0;

    bar.addEventListener("mousedown", function (e) {
      if (e.target.classList.contains("designer-stage-bar-text") && e.detail >= 2) return;
      e.preventDefault();
      dragging = true;
      startX = e.clientX;
      startOffset = stageOffset;
      bar.style.cursor = "grabbing";
    });

    document.addEventListener("mousemove", function (e) {
      if (!dragging) return;
      var area = getDataArea();
      if (!area) return;
      var colWidth = area.width / cols;
      var dx = e.clientX - startX;
      var colDelta = Math.round(dx / colWidth);
      var newOffset = Math.max(0, Math.min(cols - stageCols, startOffset + colDelta));
      stageOffset = newOffset;
      updateStageBar();
    });

    document.addEventListener("mouseup", function () {
      if (dragging) {
        dragging = false;
        bar.style.cursor = "grab";
      }
    });
  }

  function updateStageLabelDisplay() {
    var bar = document.getElementById("designer-stage-bar");
    if (!bar) return;
    var textEl = bar.querySelector(".designer-stage-bar-text");
    if (!textEl) return;
    textEl.textContent = stageLabel.toUpperCase();
    textEl.style.cursor = "text";
    textEl.title = "Double-click to edit stage label";
    textEl.addEventListener("dblclick", function (e) {
      e.stopPropagation();
      textEl.contentEditable = "true";
      textEl.style.outline = "1px solid #00d4ff";
      textEl.style.borderRadius = "3px";
      textEl.style.padding = "0 4px";
      textEl.textContent = stageLabel;
      textEl.focus();
      var range = document.createRange();
      range.selectNodeContents(textEl);
      var sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
    });
    function commitEdit() {
      textEl.contentEditable = "false";
      textEl.style.outline = "";
      textEl.style.padding = "";
      var val = textEl.textContent.trim();
      if (val) stageLabel = val;
      textEl.textContent = stageLabel.toUpperCase();
    }
    textEl.addEventListener("blur", commitEdit);
    textEl.addEventListener("keydown", function (e) {
      if (e.key === "Enter") { e.preventDefault(); textEl.blur(); }
      if (e.key === "Escape") { textEl.textContent = stageLabel; textEl.blur(); }
    });
  }

  /* ---- Preview (picker-style rendering) ---- */

  function openPreview() {
    var overlay = document.getElementById("preview-overlay");
    if (!overlay) return;
    overlay.classList.add("preview-open");
    renderPreview();
  }

  function closePreview() {
    var overlay = document.getElementById("preview-overlay");
    if (overlay) overlay.classList.remove("preview-open");
  }

  function renderPreview() {
    var container = document.getElementById("preview-seat-map");
    var stageEl = document.getElementById("preview-stage");
    var anchor = document.getElementById("preview-marker-anchor");
    if (!container) return;
    container.innerHTML = "";

    var colTemplate = "24px";
    for (var ci = 1; ci <= cols; ci++) {
      colTemplate += " 36px";
      if (ci < cols && colGaps[ci]) colTemplate += " 14px";
    }
    container.style.gridTemplateColumns = colTemplate;

    function gridColP(dataCol) {
      var gc = 1 + dataCol;
      for (var g = 1; g < dataCol; g++) {
        if (colGaps[g]) gc++;
      }
      return gc;
    }

    var gridRowP = 1;
    for (var r = 1; r <= rows; r++) {
      var rowLabel = document.createElement("div");
      rowLabel.className = "seat-row-label";
      rowLabel.textContent = rowLetter(r);
      rowLabel.style.gridRow = gridRowP;
      rowLabel.style.gridColumn = "1";
      container.appendChild(rowLabel);

      for (var c = 1; c <= cols; c++) {
        var key = r + "-" + c;
        var el = document.createElement("div");
        el.style.gridRow = gridRowP;
        el.style.gridColumn = String(gridColP(c));

        if (!grid[key] || grid[key].type === "aisle") {
          el.className = "seat seat-empty-hidden";
          el.style.visibility = "hidden";
        } else {
          var seatType = grid[key].type;
          if (isCustomType(seatType) && customTypes[seatType]) {
            el.className = "seat seat-custom";
            el.style.backgroundColor = customTypes[seatType].colour;
            el.title = grid[key].label + " \u2014 " + customTypes[seatType].name;
          } else {
            var cssClass = "seat seat-available";
            if (seatType === "vip") cssClass = "seat seat-vip";
            else if (seatType === "accessible") cssClass = "seat seat-accessible";
            el.className = cssClass;
            el.title = grid[key].label + " \u2014 " + seatType;
          }
        }
        container.appendChild(el);
      }

      gridRowP++;
      if (rowGaps[r]) gridRowP++;
    }

    if (stageEl) {
      var effectiveCols = Math.min(stageCols, cols);
      var previewSeats = container.querySelectorAll(".seat");
      var firstSeat = null, lastSeat = null;
      var containerRect = container.getBoundingClientRect();
      previewSeats.forEach(function (s) {
        if (s.style.visibility === "hidden") return;
        var r = s.getBoundingClientRect();
        if (!firstSeat || r.left < firstSeat.left) firstSeat = r;
        if (!lastSeat || r.right > lastSeat.right) lastSeat = r;
      });
      if (firstSeat && lastSeat) {
        var dataLeft = firstSeat.left - containerRect.left;
        var dataWidth = lastSeat.right - firstSeat.left;
        var colW = dataWidth / cols;
        var sw = effectiveCols * colW;
        stageEl.style.width = Math.round(sw) + "px";
        stageEl.style.marginLeft = Math.round(dataLeft + stageOffset * colW) + "px";
      }
      var labelEl = stageEl.querySelector(".stage-label");
      if (labelEl) labelEl.textContent = stageLabel;
    }

    if (anchor) {
      anchor.querySelectorAll(".picker-entry-exit").forEach(function (el) { el.remove(); });
      entryExitMarkers.forEach(function (m) {
        var mel = document.createElement("div");
        mel.className = "picker-entry-exit marker-" + m.type;
        mel.textContent = m.label || m.type;
        mel.style.position = "absolute";
        mel.style.transform = "translate(-50%, -50%)";
        mel.style.left = (m.x != null ? m.x : 50) + "%";
        mel.style.top = (m.y != null ? m.y : 0) + "%";
        anchor.appendChild(mel);
      });
    }

    adjustPreviewWrapperForMarkers();
  }

  function adjustPreviewWrapperForMarkers() {
    var wrapper = document.getElementById("preview-wrapper");
    var anchor = document.getElementById("preview-marker-anchor");
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

  function bindPreview() {
    var btn = document.getElementById("preview-layout");
    if (btn) btn.addEventListener("click", openPreview);
    var closeBtn = document.getElementById("preview-close");
    if (closeBtn) closeBtn.addEventListener("click", closePreview);
    var overlay = document.getElementById("preview-overlay");
    if (overlay) {
      overlay.addEventListener("click", function (e) {
        if (e.target === overlay) closePreview();
      });
    }
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") closePreview();
    });
  }

  window.SeatDesigner = { init: init };
})();
