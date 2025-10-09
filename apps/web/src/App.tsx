import { Routes, Route, useLocation } from "react-router-dom";
import TopNav from "./components/TopNav";
import LandingPage from "./features/landing/pages/LandingPage";
import AuthPage from "./features/auth/pages/AuthPage";
import SignInPage from "./features/auth/pages/SignInPage";
import SignUpPage from "./features/auth/pages/SignUpPage";
import ResetPage from "./features/auth/pages/ResetPage";
import TasteOnboardingPage from "./features/taste_onboarding/pages/TasteOnboardingPage";
import QueryRecommendationPage from "./features/recommendation/pages/QueryRecommendationPage";
import DiscoverPage from "./features/discover/pages/DiscoverPage";

export default function App() {
  const location = useLocation();

  return (
    <>
      <TopNav />
      <Routes location={location} key={location.key}>
        <Route path="/" element={<LandingPage />} />
        <Route path="/query" element={<QueryRecommendationPage />} />
        <Route path="/auth" element={<AuthPage />} />
        <Route path="/auth/signin" element={<SignInPage />} />
        <Route path="/auth/signup" element={<SignUpPage />} />
        <Route path="/auth/reset" element={<ResetPage />} />
        <Route path="/taste" element={<TasteOnboardingPage />} />
        <Route path="/discover" element={<DiscoverPage />} />
      </Routes>
    </>
  );
}
