export function LoadingScreen() {
  return (
    <div className="flex flex-col items-center justify-center h-screen bg-transparent">
      <div className="w-12 h-12 rounded-full bg-gradient-to-br from-amber-200 to-rose-200 animate-pulse" />
      <p className="mt-3 text-xs text-gray-400">正在启动...</p>
    </div>
  );
}
