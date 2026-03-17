/**
 * Reusable image upload widget.
 *
 * Usage:
 *   initImageUpload('input-id', '/admin/upload-image')
 *
 * Enhances an existing <input type="url"> by adding an upload button,
 * thumbnail preview, and remove button alongside it.
 */
function initImageUpload(inputId, uploadUrl) {
  var input = document.getElementById(inputId);
  if (!input || input.dataset.uploadInit) return;
  input.dataset.uploadInit = '1';

  var wrapper = document.createElement('div');
  wrapper.className = 'img-upload-wrap';
  input.parentNode.insertBefore(wrapper, input);
  wrapper.appendChild(input);

  var controls = document.createElement('div');
  controls.className = 'img-upload-controls';

  var fileInput = document.createElement('input');
  fileInput.type = 'file';
  fileInput.accept = 'image/jpeg,image/png,image/gif,image/webp';
  fileInput.style.display = 'none';

  var uploadBtn = document.createElement('button');
  uploadBtn.type = 'button';
  uploadBtn.className = 'btn img-upload-btn';
  uploadBtn.textContent = 'Upload';

  var spinner = document.createElement('span');
  spinner.className = 'img-upload-spinner';
  spinner.style.display = 'none';
  spinner.textContent = 'Uploading\u2026';

  controls.appendChild(fileInput);
  controls.appendChild(uploadBtn);
  controls.appendChild(spinner);
  wrapper.appendChild(controls);

  var preview = document.createElement('div');
  preview.className = 'img-upload-preview';
  preview.style.display = 'none';

  var previewImg = document.createElement('img');
  previewImg.alt = 'Preview';

  var removeBtn = document.createElement('button');
  removeBtn.type = 'button';
  removeBtn.className = 'img-upload-remove';
  removeBtn.title = 'Remove image';
  removeBtn.innerHTML = '&times;';

  preview.appendChild(previewImg);
  preview.appendChild(removeBtn);
  wrapper.appendChild(preview);

  function showPreview() {
    var val = input.value.trim();
    if (val) {
      previewImg.src = val;
      preview.style.display = 'inline-block';
    } else {
      preview.style.display = 'none';
      previewImg.src = '';
    }
  }

  showPreview();

  input.addEventListener('input', showPreview);
  input.addEventListener('change', showPreview);

  uploadBtn.addEventListener('click', function () {
    fileInput.click();
  });

  removeBtn.addEventListener('click', function () {
    input.value = '';
    preview.style.display = 'none';
    previewImg.src = '';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
  });

  fileInput.addEventListener('change', function () {
    if (!fileInput.files || !fileInput.files[0]) return;
    var file = fileInput.files[0];

    if (file.size > 5 * 1024 * 1024) {
      alert('File too large (max 5 MB)');
      fileInput.value = '';
      return;
    }

    spinner.style.display = 'inline';
    uploadBtn.style.display = 'none';

    var fd = new FormData();
    fd.append('image', file);

    var csrfEl = document.querySelector('input[name="csrf_token"]');
    if (csrfEl) fd.append('csrf_token', csrfEl.value);

    fetch(uploadUrl, { method: 'POST', body: fd })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.url) {
          input.value = data.url;
          showPreview();
          input.dispatchEvent(new Event('input', { bubbles: true }));
          input.dispatchEvent(new Event('change', { bubbles: true }));
        } else {
          alert(data.error || 'Upload failed');
        }
      })
      .catch(function (e) {
        alert('Upload failed: ' + e.message);
      })
      .finally(function () {
        spinner.style.display = 'none';
        uploadBtn.style.display = '';
        fileInput.value = '';
      });
  });
}
