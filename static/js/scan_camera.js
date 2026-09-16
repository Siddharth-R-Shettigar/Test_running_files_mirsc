(async function () {
  const video = document.getElementById("cam");
  const canvas = document.getElementById("shot");
  const status = document.getElementById("cam-status");
  const btn = document.getElementById("btn-capture");
  const form = document.getElementById("capture-form");
  const input = document.getElementById("frame-input");

  if (!video || !btn) return;

  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: "environment" } },
      audio: false,
    });
    video.srcObject = stream;
    status.textContent = "Camera ready — press capture when aligned.";
    btn.disabled = false;
  } catch (err) {
    status.textContent =
      "Camera blocked or unavailable. Allow camera permission and reload (HTTPS or localhost required).";
    console.error(err);
    return;
  }

  btn.addEventListener("click", () => {
    const w = video.videoWidth || 1280;
    const h = video.videoHeight || 720;
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(video, 0, 0, w, h);

    canvas.toBlob(
      (blob) => {
        if (!blob) {
          status.textContent = "Capture failed. Try again.";
          return;
        }
        const file = new File([blob], "capture.jpg", { type: "image/jpeg" });
        const dt = new DataTransfer();
        dt.items.add(file);
        input.files = dt.files;
        status.textContent = "Captured — uploading…";
        form.submit();
      },
      "image/jpeg",
      0.92
    );
  });
})();