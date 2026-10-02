const dropZone = document.getElementById('dropZone');
const fileInput = document.getElementById('fileInput');
const fileInfo = document.getElementById('fileInfo');
const btnSubmit = document.getElementById('btnSubmit');

['dragover','dragenter'].forEach(ev => dropZone.addEventListener(ev, e => { e.preventDefault(); dropZone.classList.add('dragover'); }));
['dragleave','drop'].forEach(ev => dropZone.addEventListener(ev, () => dropZone.classList.remove('dragover')));
dropZone.addEventListener('drop', e => {
  e.preventDefault();
  if (e.dataTransfer.files.length) {
    fileInput.files = e.dataTransfer.files;
    updateInfo();
  }
});
fileInput.addEventListener('change', updateInfo);
function updateInfo() {
  if (fileInput.files.length) {
    const f = fileInput.files[0];
    fileInfo.textContent = `✓ ${f.name} (${(f.size/1024).toFixed(1)} Ko)`;
    btnSubmit.disabled = false;
  } else {
    fileInfo.textContent = '';
    btnSubmit.disabled = true;
  }
}
