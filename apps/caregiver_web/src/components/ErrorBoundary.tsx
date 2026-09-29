import { Component, type ReactNode } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

interface Props { children: ReactNode }
interface State { error: Error | null }

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <div className="flex flex-col items-start gap-4 rounded-xl border border-red-200 bg-red-50 dark:bg-red-950/20 p-6">
          <div className="flex items-center gap-2 text-red-700 dark:text-red-400">
            <AlertTriangle className="size-5" />
            <span className="font-semibold">Component crashed</span>
          </div>
          <pre className="w-full overflow-auto rounded-lg bg-white dark:bg-black/30 p-3 text-xs text-red-800 dark:text-red-300 border border-red-200">
            {this.state.error.message}
            {"\n\n"}
            {this.state.error.stack}
          </pre>
          <button
            onClick={() => this.setState({ error: null })}
            className="flex items-center gap-1.5 rounded-lg bg-red-100 dark:bg-red-900/30 px-3 py-1.5 text-sm font-medium text-red-700 dark:text-red-400 hover:bg-red-200 transition-colors"
          >
            <RefreshCw className="size-3.5" />
            Retry
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
