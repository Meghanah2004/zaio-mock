import { AppShell } from "./components/AppShell";
import { About } from "./pages/About";
import { Dashboard } from "./pages/Dashboard";
import { Documentation } from "./pages/Documentation";
import { useRoute } from "./hooks/useRoute";
import { RouterProvider } from "./router";

function Routes() {
  const { pathname } = useRoute();

  let page;
  if (pathname === "/documentation") {
    page = <Documentation />;
  } else if (pathname === "/about") {
    page = <About />;
  } else {
    // "/", "/assessments", "/assessments/:id", and any unrecognized path
    // all render the same workspace - Dashboard itself reads an :id out of
    // the URL on mount when there is one (see pages/Dashboard.tsx).
    page = <Dashboard />;
  }

  return <AppShell>{page}</AppShell>;
}

function App() {
  return (
    <RouterProvider>
      <Routes />
    </RouterProvider>
  );
}

export default App;
