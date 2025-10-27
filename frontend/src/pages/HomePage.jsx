import { useState } from "react";
import { useNavigate } from "react-router-dom";
import EmailPage from "../components/EmailStep";
import QuestionsPage from "../components/QuestionsStep";
import RecipientsPage from "../components/RecipientsStep";
import TraitsPage from "../components/TraitsStep";
import Arrow from "../icons/arrow.svg?react";
import { doc, setDoc, serverTimestamp } from "firebase/firestore";
import { db } from "../components/Firebase";

export default function HomePage() {
  const [questions, setQuestions] = useState([""]);
  const [traits, setTraits] = useState([""]);
  const [recipients, setRecipients] = useState([""]);
  const [email, setEmail] = useState("");
  const [step, setStep] = useState(0);

  const [canContinue, setCanContinue] = useState(false);
  const [error, setError] = useState(false);

  const navigate = useNavigate();

  function back() {
    setStep(step - 1);
  }

  function nextStep() {
    if (!canContinue) {
      setError(true);
      return;
    }
    setError(false);
    setStep(step + 1);
  }

  async function saveSessionData(id, data) {
    const ref = doc(db, "sessions", id);
    console.log("Saving session data to Firestore with ID:", id);
    try {
      await setDoc(ref, {
        ...data,
        createdAt: serverTimestamp(),
      });
      console.log("Session data saved successfully to Firestore with ID:", id);
    } catch (firestoreError) {
      console.error("Error saving session data to Firestore:", firestoreError);
    }
  }

  async function send() {
    if (!email || questions.filter(q => q.trim() !== "").length === 0 || traits.filter(t => t.trim() !== "").length === 0 || recipients.filter(r => r.trim() !== "").length === 0) {
      setError(true);
      console.error("Validation failed: Missing required fields.");
      return;
    }
    setError(false);

    const payload = {
      questions: questions.filter(q => q.trim() !== ""),
      traits: traits.filter(t => t.trim() !== ""),
      employer_email: email,
      applicant_emails: recipients.filter(r => r.trim() !== ""),
    };

    try {
      console.log("Sending data to backend:", payload);
      const response = await fetch('http://127.0.0.1:5000/create-interview', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        const errorData = await response.json();
        console.error("Backend error response:", errorData);
        throw new Error(errorData.error || `HTTP error! status: ${response.status}`);
      }

      const responseData = await response.json();
      console.log("Backend response:", responseData);

      const backendInterviewId = responseData.interview_link.split('/').pop();
      await saveSessionData(backendInterviewId, {
        email,
        questions: payload.questions,
        traits: payload.traits,
        recipients: payload.applicant_emails,
        reportLink: responseData.report_link,
      });

      navigate(`/created`, {
        state: {
          id: backendInterviewId,
          reportLink: responseData.report_link,
        },
      });

    } catch (fetchError) {
      console.error("Error during send process:", fetchError);
      setError(fetchError.message || "Failed to create interview. Please check the connection or try again.");
    }
  }

  var page = null;
  switch (step) {
    case 0:
      page = (
        <EmailPage
          email={email}
          setEmail={setEmail}
          error={error}
          setError={setError}
          setCanContinue={setCanContinue}
        />
      );
      break;
    case 1:
      page = (
        <QuestionsPage
          questions={questions}
          setQuestions={setQuestions}
          setCanContinue={setCanContinue}
        />
      );
      break;
    case 2:
      page = (
       <TraitsPage
          traits={traits}
          setTraits={setTraits}
          setCanContinue={setCanContinue}
        />
      );
      break;
    case 3:
      page = (
        <RecipientsPage
          recipients={recipients}
          setRecipients={setRecipients}
          setCanContinue={setCanContinue}
        />
      );
      break;
    default:
      page = <div>Invalid step</div>;
  }

  return (
    <div>
      <div className="absolute px-10 h-15 outline flex justify-center items-center w-screen outline-gray-500 header">
        <h1 className="absolute h-15 flex justify-center items-center top-0 right-10 text-lg font-black title">
          interdex.ai
        </h1>
        {step > 0 ? (
          <h1 className="text-lg text-gray-800 bg-white px-3 py-2 rounded-2xl">
            {email}
          </h1>
        ) : null}
      </div>
      <div className="h-screen py-40 flex flex-col items-center justify-between relative">
        {page}

        {error && typeof error === 'string' && (
          <div className="absolute top-20 text-red-500 bg-red-100 p-2 rounded">
            Error: {error}
          </div>
        )}

        {step > 0 ? (
          <div className="absolute left-20">
            <button
              className="cursor-pointer text-grey-500 text-md focus-gap relative h-10 w-20"
              onClick={back}
            >
              Back
              <div className="absolute top-0 h-10 flex items-center arrow flipped">
                <Arrow className="size-4 arrow-svg" />
              </div>
            </button>
          </div>
        ) : null}

        <div className="absolute bottom-20">
          {step < 3 ? (
            <button
              className="cursor-pointer text-grey-500 text-2xl focus-gap relative h-10 w-30 mb-5 disabled:opacity-50"
              onClick={nextStep}
              disabled={!canContinue && step !== 0}
            >
              Next
              <div className="absolute top-0 h-10 flex items-center arrow right">
                <Arrow className="size-5 arrow-svg" />
              </div>
            </button>
          ) : (
            <button
              className="cursor-pointer px-10 py-5 text-white text-2xl bg-gray-900 rounded-3xl send-btn disabled:opacity-50"
              onClick={send}
              disabled={!canContinue}
            >
              Send
            </button>
          )}
        </div>
      </div>
    </div>
  );
}