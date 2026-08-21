import React, { lazy } from 'react';
import {
  AlarmClock,
  Bell,
  Brain,
  CalendarDays,
  ChartNoAxesCombined,
  CloudSun,
  Code2,
  Cpu,
  FolderGit2,
  FolderOpen,
  GitBranch,
  GitGraph,
  Globe2,
  ListTodo,
  Music2,
  Newspaper,
  Search,
  SearchCode,
  ShieldCheck,
  Sparkles,
  SquareTerminal,
  Telescope,
} from 'lucide-react';

// Lazy loading all widget components to optimize bundle footprint and render speed
const TodoWidget = lazy(() => import('./TodoWidget'));
const CalendarWidget = lazy(() => import('./CalendarWidget'));
const GitWidget = lazy(() => import('./GitWidget'));
const FileExplorerWidget = lazy(() => import('./FileExplorerWidget'));
const UniversalSearchWidget = lazy(() => import('./UniversalSearchWidget'));
const DeepResearchWidget = lazy(() => import('./DeepResearchWidget'));
const WeatherWidget = lazy(() => import('./WeatherWidget'));
const MarketWidget = lazy(() => import('./MarketWidget'));
const TerminalWidget = lazy(() => import('./TerminalWidget'));
const MemoryWidget = lazy(() => import('./MemoryWidget'));
const NotificationWidget = lazy(() => import('./NotificationWidget'));
const SystemWidget = lazy(() => import('./SystemWidget'));
const ReminderWidget = lazy(() => import('./ReminderWidget'));
const CodeOptimizerWidget = lazy(() => import('./CodeOptimizerWidget'));
const SemanticCodeGraphWidget = lazy(() => import('./SemanticCodeGraphWidget'));
const SecurityGuardianWidget = lazy(() => import('./SecurityGuardianWidget'));
const DailyBriefingWidget = lazy(() => import('./DailyBriefingWidget'));
const CodingWidget = lazy(() => import('./CodingWidget'));
const MusicWidget = lazy(() => import('./MusicWidget'));
const WorldMonitorWidget = lazy(() => import('./WorldMonitorWidget'));
const GithubSearchWidget = lazy(() => import('./GithubSearchWidget'));
const GitCloneWidget = lazy(() => import('./GitCloneWidget'));

/**
 * Standardized Frontend Widget Registry Map (OCP Compliant)
 * Every widget implements a common interface containing: id, title, category, default dimensions, and Component.
 * Enables dynamic registration, mounting, and destruction of widgets without altering the AppShell.
 */
export const WIDGET_REGISTRY = {
  todo: {
    id: "todo",
    icon: ListTodo,
    title: "Daily Task Manager",
    category: "productivity",
    defaultWidth: 320,
    defaultHeight: 280,
    Component: TodoWidget
  },
  calendar: {
    id: "calendar",
    icon: CalendarDays,
    title: "Day Planner & Schedule",
    category: "productivity",
    defaultWidth: 320,
    defaultHeight: 240,
    Component: CalendarWidget
  },
  reminder: {
    id: "reminder",
    icon: AlarmClock,
    title: "Reminder & Alarm Core",
    category: "system",
    defaultWidth: 320,
    defaultHeight: 300,
    Component: ReminderWidget
  },
  code_optimizer: {
    id: "code_optimizer",
    icon: Sparkles,
    title: "SOLID Code Optimizer",
    category: "system",
    defaultWidth: 320,
    defaultHeight: 300,
    Component: CodeOptimizerWidget
  },
  semantic_code_graph: {
    id: "semantic_code_graph",
    icon: GitGraph,
    title: "Semantic Code Graph",
    category: "system",
    defaultWidth: 320,
    defaultHeight: 300,
    Component: SemanticCodeGraphWidget
  },
  coding: {
    id: "coding",
    icon: Code2,
    title: "Coding Agent",
    category: "developer",
    defaultWidth: 340,
    defaultHeight: 240,
    Component: CodingWidget
  },
  music: {
    id: "music",
    icon: Music2,
    title: "Music Player",
    category: "music",
    defaultWidth: 320,
    defaultHeight: 220,
    Component: MusicWidget
  },
  world_monitor: {
    id: "world_monitor",
    icon: Globe2,
    title: "World Monitor",
    category: "research",
    defaultWidth: 320,
    defaultHeight: 260,
    Component: WorldMonitorWidget
  },
  github_search: {
    id: "github_search",
    icon: SearchCode,
    title: "GitHub Search",
    category: "developer",
    defaultWidth: 320,
    defaultHeight: 240,
    Component: GithubSearchWidget
  },
  git_clone: {
    id: "git_clone",
    icon: FolderGit2,
    title: "Git Clone",
    category: "developer",
    defaultWidth: 340,
    defaultHeight: 260,
    Component: GitCloneWidget
  },
  security_guardian: {
    id: "security_guardian",
    icon: ShieldCheck,
    title: "Security Guardian",
    category: "system",
    defaultWidth: 320,
    defaultHeight: 300,
    Component: SecurityGuardianWidget
  },
  daily_briefing: {
    id: "daily_briefing",
    icon: Newspaper,
    title: "Daily Briefing Engine",
    category: "productivity",
    defaultWidth: 320,
    defaultHeight: 300,
    Component: DailyBriefingWidget
  },
  git: {
    id: "git",
    icon: GitBranch,
    title: "Git Repository Watcher",
    category: "developer",
    defaultWidth: 320,
    defaultHeight: 300,
    Component: GitWidget
  },
  file_explorer: {
    id: "file_explorer",
    icon: FolderOpen,
    title: "Local File Explorer",
    category: "system",
    defaultWidth: 340,
    defaultHeight: 260,
    Component: FileExplorerWidget
  },
  universal_search: {
    id: "universal_search",
    icon: Search,
    title: "Universal search Engine",
    category: "system",
    defaultWidth: 320,
    defaultHeight: 260,
    Component: UniversalSearchWidget
  },
  deep_research: {
    id: "deep_research",
    icon: Telescope,
    title: "Deep AI Research",
    category: "research",
    defaultWidth: 320,
    defaultHeight: 280,
    Component: DeepResearchWidget
  },
  weather: {
    id: "weather",
    icon: CloudSun,
    title: "Local Weather Watcher",
    category: "productivity",
    defaultWidth: 320,
    defaultHeight: 280,
    Component: WeatherWidget
  },
  market: {
    id: "market",
    icon: ChartNoAxesCombined,
    title: "Live Market Index",
    category: "productivity",
    defaultWidth: 320,
    defaultHeight: 220,
    Component: MarketWidget
  },
  terminal: {
    id: "terminal",
    icon: SquareTerminal,
    title: "Terminal Subprocess logs",
    category: "developer",
    defaultWidth: 340,
    defaultHeight: 240,
    Component: TerminalWidget
  },
  memory: {
    id: "memory",
    icon: Brain,
    title: "Memory DB Viewer",
    category: "memory",
    defaultWidth: 320,
    defaultHeight: 280,
    Component: MemoryWidget
  },
  notification: {
    id: "notification",
    icon: Bell,
    title: "System Notification Hub",
    category: "system",
    defaultWidth: 320,
    defaultHeight: 240,
    Component: NotificationWidget
  },
  system: {
    id: "system",
    icon: Cpu,
    title: "Hardware System Metrics",
    category: "system",
    defaultWidth: 320,
    defaultHeight: 280,
    Component: SystemWidget
  }
};
