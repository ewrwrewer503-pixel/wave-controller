# Wave Controller

## How to get the Windows .exe (no Windows PC needed)

1. Create a new repository on GitHub (public or private, either works) and
   upload these files, keeping the folder structure:
   - `wavefix.py`
   - `.github/workflows/build.yml`
2. Once pushed, click the **Actions** tab at the top of the repo.
3. You'll see a run called "Build WaveController.exe" — click it (it starts
   automatically on push, or click **Run workflow** to trigger it manually).
4. Wait 1-2 minutes for it to finish (green checkmark).
5. Scroll down to the **Artifacts** section of that run and click
   **WaveController-windows-exe** to download a zip containing your
   ready-to-use `WaveController.exe`.
6. Unzip it and share the `.exe` with anyone — it runs standalone on
   Windows, no Python required.
