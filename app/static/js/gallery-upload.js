/**
 * Gallery image upload widget with drag-to-reorder.
 *
 * Usage:
 *   initGalleryUpload('gallery-container-id', '/admin/upload-image', [
 *     {id: 1, url: '/uploads/1'},
 *     {id: 2, url: '/uploads/2'},
 *   ]);
 *
 * The hidden input #gallery-image-ids gets updated with a comma-separated
 * list of image IDs whenever images are added, removed, or reordered.
 */
function initGalleryUpload(containerId, uploadUrl, existingImages) {
  var container = document.getElementById(containerId);
  if (!container) return;

  var grid = container.querySelector('.gallery-grid');
  var hiddenInput = container.querySelector('.gallery-ids-input');
  var addBtn = container.querySelector('.gallery-add-btn');
  var fileInput = document.createElement('input');
  fileInput.type = 'file';
  fileInput.accept = 'image/jpeg,image/png,image/gif,image/webp';
  fileInput.multiple = true;
  fileInput.style.display = 'none';
  container.appendChild(fileInput);

  var images = (existingImages || []).slice();

  function render() {
    grid.innerHTML = '';
    images.forEach(function (img, idx) {
      var item = document.createElement('div');
      item.className = 'gallery-item';
      item.draggable = true;
      item.dataset.idx = idx;

      var imgEl = document.createElement('img');
      imgEl.src = img.url;
      imgEl.alt = 'Gallery image ' + (idx + 1);

      var badge = document.createElement('span');
      badge.className = 'gallery-item-badge';
      badge.textContent = idx + 1;

      var removeBtn = document.createElement('button');
      removeBtn.type = 'button';
      removeBtn.className = 'gallery-item-remove';
      removeBtn.innerHTML = '&times;';
      removeBtn.title = 'Remove';
      removeBtn.addEventListener('click', function () {
        images.splice(idx, 1);
        syncAndRender();
      });

      item.appendChild(imgEl);
      item.appendChild(badge);
      item.appendChild(removeBtn);
      grid.appendChild(item);

      item.addEventListener('dragstart', function (e) {
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', idx.toString());
        item.classList.add('dragging');
      });
      item.addEventListener('dragend', function () {
        item.classList.remove('dragging');
      });
      item.addEventListener('dragover', function (e) {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        item.classList.add('drag-over');
      });
      item.addEventListener('dragleave', function () {
        item.classList.remove('drag-over');
      });
      item.addEventListener('drop', function (e) {
        e.preventDefault();
        item.classList.remove('drag-over');
        var fromIdx = parseInt(e.dataTransfer.getData('text/plain'));
        var toIdx = idx;
        if (fromIdx === toIdx) return;
        var moved = images.splice(fromIdx, 1)[0];
        images.splice(toIdx, 0, moved);
        syncAndRender();
      });
    });

    syncHidden();
  }

  function syncHidden() {
    if (hiddenInput) {
      hiddenInput.value = images.map(function (img) { return img.id; }).join(',');
    }
  }

  function syncAndRender() {
    render();
  }

  addBtn.addEventListener('click', function () {
    fileInput.click();
  });

  fileInput.addEventListener('change', function () {
    if (!fileInput.files || !fileInput.files.length) return;
    var files = Array.from(fileInput.files);
    var pending = files.length;

    addBtn.disabled = true;
    addBtn.textContent = 'Uploading\u2026';

    files.forEach(function (file) {
      if (file.size > 5 * 1024 * 1024) {
        alert('File "' + file.name + '" is too large (max 5 MB)');
        pending--;
        if (pending === 0) { addBtn.disabled = false; addBtn.textContent = '+ Add Images'; }
        return;
      }

      var fd = new FormData();
      fd.append('image', file);
      var csrfEl = document.querySelector('input[name="csrf_token"]');
      if (csrfEl) fd.append('csrf_token', csrfEl.value);

      fetch(uploadUrl, { method: 'POST', body: fd })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data.url) {
            var imgId = data.url.replace('/uploads/', '');
            images.push({ id: parseInt(imgId), url: data.url });
          } else {
            alert(data.error || 'Upload failed for ' + file.name);
          }
        })
        .catch(function (e) {
          alert('Upload failed: ' + e.message);
        })
        .finally(function () {
          pending--;
          if (pending === 0) {
            addBtn.disabled = false;
            addBtn.textContent = '+ Add Images';
            fileInput.value = '';
            syncAndRender();
          }
        });
    });
  });

  render();
}
