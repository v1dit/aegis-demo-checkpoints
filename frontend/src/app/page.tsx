export default function Home() {
  return (
    <main style={{ padding: "2rem", background: "#0b0f14", color: "#e8eef6", minHeight: "100vh" }}>
      <h1 style={{ fontSize: "1.8rem", marginBottom: "1rem" }}>PantherHacks SOC Dashboard (Track B Integration Point)</h1>
      <p>
        Track A backend contracts are ready. Connect this UI to <code>/stream/replay/:replay_id</code> and
        <code> /stream/live/:session_id</code> plus the train/eval/replay APIs.
      </p>
    </main>
  );
}
