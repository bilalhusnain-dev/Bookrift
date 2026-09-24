const photoUrls = {};
let stream = null;
let cameraKind = '';
let cameraRequest = 0;
let cameraReminder = null;

function clearCameraReminder() {
  clearTimeout(cameraReminder);
  cameraReminder = null;
}

function element(id) {
  return document.getElementById(id);
}

// Selected file aur preview dono clear karne hain.
export function clearPhoto(kind) {
  element(kind + '-image').value = '';
  const preview = element(kind + '-preview');
  preview.hidden = true;
  preview.removeAttribute('src');
  if (photoUrls[kind]) URL.revokeObjectURL(photoUrls[kind]);
  delete photoUrls[kind];
  element(kind + '-prompt').hidden = false;
  element(kind + '-remove').hidden = true;
  element(kind + '-photo-message').textContent = '';
}

function showPhoto(kind) {
  const input = element(kind + '-image');
  const file = input.files[0];
  if (!file) return;
  if (photoUrls[kind]) URL.revokeObjectURL(photoUrls[kind]);
  photoUrls[kind] = URL.createObjectURL(file);
  const preview = element(kind + '-preview');
  preview.src = photoUrls[kind];
  preview.hidden = false;
  element(kind + '-prompt').hidden = true;
  element(kind + '-remove').hidden = false;
  element(kind + '-photo-message').textContent = '';
}

function usePhoto(kind, file) {
  const files = new DataTransfer();
  files.items.add(file);
  element(kind + '-image').files = files.files;
  showPhoto(kind);
}

function stopStream(value) {
  if (!value) return;
  for (const track of value.getTracks()) track.stop();
}

// Dialog band karte waqt camera stream bhi stop karni hai.
export function closeCamera() {
  cameraRequest += 1;
  clearCameraReminder();
  stopStream(stream);
  stream = null;
  element('camera-video').srcObject = null;
  const dialog = element('camera-dialog');
  if (dialog.open) dialog.close();
}

// Permission ke baad live preview; error ho to upload ka option rahega.
async function openCamera(kind) {
  closeCamera();
  cameraKind = kind;
  const request = cameraRequest;
  element('camera-title').textContent = 'Take a ' + kind + ' photo';
  element('camera-message').textContent = 'Opening camera. Allow camera access if asked.';
  element('camera-capture').disabled = true;
  element('camera-dialog').showModal();
  cameraReminder = setTimeout(() => {
    if (request !== cameraRequest) return;
    element('camera-message').textContent =
      'Still waiting for the camera. Check camera permission, choose a photo, or cancel.';
  }, 10000);
  try {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error('CameraUnavailable');
    }
    const opened = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: { facingMode: 'environment', width: { ideal: 1920 }, height: { ideal: 1080 } },
    });
    if (request !== cameraRequest) {
      stopStream(opened);
      return;
    }
    stream = opened;
    const video = element('camera-video');
    video.srcObject = opened;
    await video.play();
    if (request !== cameraRequest) return;
    clearCameraReminder();
    element('camera-capture').disabled = false;
    element('camera-message').textContent = 'Keep the image steady and the text in focus.';
  } catch (error) {
    if (request !== cameraRequest) return;
    clearCameraReminder();
    stopStream(stream);
    stream = null;
    element('camera-video').srcObject = null;
    let message = 'Camera unavailable. Select Choose photo to use an image from your device.';
    if (error.name === 'NotAllowedError') {
      message = 'Camera permission denied. Allow camera access, or cancel and upload a photo.';
    } else if (error.name === 'NotReadableError') {
      message = 'Camera is busy. Close other camera apps and try again, or upload a photo.';
    } else if (error.name === 'NotFoundError') {
      message = 'No camera found. Connect a camera, or select Choose photo.';
    }
    element('camera-message').textContent = message;
  }
}

function capturePhoto() {
  try {
    captureFrame();
  } catch {
    element('camera-message').textContent = 'Photo could not be captured. Please upload a photo.';
    element('camera-capture').disabled = false;
  }
}

// Video ka current frame JPEG file bana kar input mein rakhna.
function captureFrame() {
  const video = element('camera-video');
  if (!video.videoWidth || !video.videoHeight) {
    element('camera-message').textContent = 'Camera is not ready yet. Please try again.';
    return;
  }
  const request = cameraRequest;
  const kind = cameraKind;
  const canvas = document.createElement('canvas');
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  canvas.getContext('2d').drawImage(video, 0, 0);
  element('camera-capture').disabled = true;
  canvas.toBlob((blob) => {
    if (request !== cameraRequest) return;
    try {
      if (!blob) throw new Error('No photo');
      usePhoto(kind, new File([blob], kind + '.jpg', { type: 'image/jpeg' }));
      closeCamera();
    } catch {
      element('camera-message').textContent = 'Photo could not be captured. Please upload a photo.';
      element('camera-capture').disabled = false;
    }
  }, 'image/jpeg', 0.92);
}

// Request chal rahi ho to photo beech mein change nahi karni.
export function setPhotoBusy(form, busy) {
  for (const control of form.querySelectorAll('[data-upload], [data-camera], .photo-remove')) {
    control.disabled = busy;
  }
  for (const input of form.querySelectorAll('input[type="file"]')) input.disabled = busy;
}

// Cover aur barcode ke buttons ko unke actions se jorna.
export function setupPhotos() {
  for (const kind of ['cover', 'barcode']) {
    element(kind + '-image').addEventListener('change', () => showPhoto(kind));
    element(kind + '-remove').addEventListener('click', () => clearPhoto(kind));
    element(kind + '-preview').addEventListener('error', () => {
      clearPhoto(kind);
      element(kind + '-photo-message').textContent = 'This photo cannot be read. Choose another image.';
    });
  }
  for (const button of document.querySelectorAll('[data-upload]')) {
    button.addEventListener('click', () => element(button.dataset.upload + '-image').click());
  }
  for (const button of document.querySelectorAll('[data-camera]')) {
    button.addEventListener('click', () => openCamera(button.dataset.camera));
  }
  element('camera-close').addEventListener('click', closeCamera);
  element('camera-cancel').addEventListener('click', closeCamera);
  element('camera-dialog').addEventListener('cancel', closeCamera);
  element('camera-capture').addEventListener('click', capturePhoto);
  element('camera-device').addEventListener('click', () => {
    clearCameraReminder();
    stopStream(stream);
    stream = null;
    cameraRequest += 1;
    element('camera-capture').disabled = true;
    element('camera-video').srcObject = null;
    element('camera-message').textContent = 'Choose a photo, or cancel and reopen Take photo to use the camera.';
    element('device-camera-input').value = '';
    element('device-camera-input').click();
  });
  element('device-camera-input').addEventListener('change', (event) => {
    const file = event.target.files[0];
    if (!file || !element('camera-dialog').open) return;
    try {
      usePhoto(cameraKind, file);
      closeCamera();
    } catch {
      element('camera-message').textContent = 'Photo could not be selected. Please use Upload instead.';
    }
  });
  window.addEventListener('pagehide', closeCamera);
  window.addEventListener('hashchange', closeCamera);
}
