export function NavProgress() {
  return (
    <div
      className="pointer-events-none fixed inset-x-0 top-0 z-50 h-0.5 overflow-hidden md:left-64"
      aria-hidden
    >
      <div className="nav-progress-bar h-full bg-blue-500" />
    </div>
  );
}
