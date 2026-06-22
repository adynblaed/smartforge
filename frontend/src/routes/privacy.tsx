import { createFileRoute } from "@tanstack/react-router"

import { H2, H3, Lead, LegalLayout, P, UL } from "@/components/Common/LegalLayout"

export const Route = createFileRoute("/privacy")({
  component: PrivacyPage,
  head: () => ({ meta: [{ title: "Privacy Policy - Future Form Manufacturing" }] }),
})

function PrivacyPage() {
  return (
    <LegalLayout title="Privacy Policy" updated="March 30, 2026">
      <P>
        This Privacy Notice for Future Form Manufacturing LLC. (“we,” “us,” or “our”),
        describes how and why we might access, collect, store, use, and/or share
        (“process”) your personal information when you use our services (“Services”),
        including when you:
      </P>
      <UL
        items={[
          <>Visit our website at https://futureform.com or any website of ours that links to this Privacy Notice.</>,
          <>Use Advanced Manufacturing for Data Center Components.</>,
          <>Engage with us in other related ways, including any marketing or events.</>,
        ]}
      />
      <P>
        Questions or concerns? Reading this Privacy Notice will help you understand
        your privacy rights and choices. We are responsible for making decisions about
        how your personal information is processed. If you do not agree with our
        policies and practices, please do not use our Services. If you still have any
        questions or concerns, please contact us at info@futureform.com.
      </P>

      <H2>Summary of Key Points</H2>
      <P>
        This summary provides key points from our Privacy Notice, but you can find out
        more details about any of these topics by using the table of contents below to
        find the section you are looking for.
      </P>
      <UL
        items={[
          <><strong>What personal information do we process?</strong> When you visit, use, or navigate our Services, we may process personal information depending on how you interact with us and the Services, the choices you make, and the products and features you use.</>,
          <><strong>Do we process any sensitive personal information?</strong> We do not process sensitive personal information.</>,
          <><strong>Do we collect any information from third parties?</strong> We may collect information from public databases, marketing partners, social media platforms, and other outside sources.</>,
          <><strong>How do we process your information?</strong> We process your information to provide, improve, and administer our Services, communicate with you, for security and fraud prevention, and to comply with law.</>,
          <><strong>In what situations and with which parties do we share personal information?</strong> We may share information in specific situations and with specific third parties.</>,
          <><strong>How do we keep your information safe?</strong> We have adequate organizational and technical processes and procedures in place to protect your personal information. However, no electronic transmission or storage can be guaranteed to be 100% secure.</>,
          <><strong>What are your rights?</strong> Depending on where you are located geographically, the applicable privacy law may mean you have certain rights regarding your personal information.</>,
          <><strong>How do you exercise your rights?</strong> The easiest way is by submitting a data subject access request, or by contacting us.</>,
        ]}
      />

      <H2>Table of Contents</H2>
      <UL
        items={[
          "1. What information do we collect?",
          "2. How do we process your information?",
          "3. What legal bases do we rely on to process your personal information?",
          "4. When and with whom do we share your personal information?",
          "5. Do we use cookies and other tracking technologies?",
          "6. How long do we keep your information?",
          "7. How do we keep your information safe?",
          "8. Do we collect information from minors?",
          "9. What are your privacy rights?",
          "10. Controls for do-not-track features",
          "11. Do United States residents have specific privacy rights?",
          "12. Do we make updates to this notice?",
          "13. How can you contact us about this notice?",
          "14. How can you review, update, or delete the data we collect from you?",
        ]}
      />

      <H2>1. What Information Do We Collect?</H2>
      <H3>Personal information you disclose to us</H3>
      <Lead>In Short: We collect personal information that you provide to us.</Lead>
      <P>
        We collect personal information that you voluntarily provide to us when you
        express an interest in obtaining information about us or our products and
        Services, when you participate in activities on the Services, or otherwise when
        you contact us. The personal information we collect may include the following:
      </P>
      <UL
        items={[
          "names",
          "phone numbers",
          "email addresses",
          "mailing addresses",
          "job titles",
          "contact preferences",
          "contact or authentication data",
        ]}
      />
      <P>
        <strong>Sensitive Information.</strong> We do not process sensitive
        information. All personal information that you provide to us must be true,
        complete, and accurate, and you must notify us of any changes to such personal
        information.
      </P>
      <H3>Information automatically collected</H3>
      <Lead>
        In Short: Some information — such as your Internet Protocol (IP) address and/or
        browser and device characteristics — is collected automatically when you visit
        our Services.
      </Lead>
      <P>
        This information does not reveal your specific identity but may include device
        and usage information, such as your IP address, browser and device
        characteristics, operating system, language preferences, referring URLs, device
        name, country, location, and information about how and when you use our
        Services. The information we collect includes log and usage data, device data,
        and location data. Like many businesses, we also collect information through
        cookies and similar technologies.
      </P>
      <H3>Information collected from other sources</H3>
      <Lead>
        In Short: We may collect limited data from public databases, marketing
        partners, and other outside sources.
      </Lead>
      <P>
        In order to enhance our ability to provide relevant marketing, offers, and
        services to you and update our records, we may obtain information about you from
        other sources, such as public databases, joint marketing partners, affiliate
        programs, data providers, and from other third parties.
      </P>

      <H2>2. How Do We Process Your Information?</H2>
      <Lead>
        In Short: We process your information to provide, improve, and administer our
        Services, communicate with you, for security and fraud prevention, and to comply
        with law.
      </Lead>
      <UL
        items={[
          "To request feedback and to contact you about your use of our Services.",
          "To send you marketing and promotional communications in accordance with your preferences.",
          "To deliver targeted advertising tailored to your interests and location.",
          "To protect our Services, including fraud monitoring and prevention.",
          "To identify usage trends so we can improve our Services.",
          "To determine the effectiveness of our marketing and promotional campaigns.",
          "To save or protect an individual’s vital interest, such as to prevent harm.",
        ]}
      />

      <H2>3. What Legal Bases Do We Rely On?</H2>
      <Lead>
        In Short: We only process your personal information when we believe it is
        necessary and we have a valid legal reason to do so under applicable law.
      </Lead>
      <P>
        If you are located in the EU or UK, the GDPR and UK GDPR require us to explain
        the valid legal bases we rely on: consent, legitimate interests, legal
        obligations, and vital interests. If you are located in Canada, we may process
        your information where you have given express or implied consent, or where we
        are legally permitted to process it without consent in certain exceptional cases.
      </P>

      <H2>4. When and With Whom Do We Share Your Information?</H2>
      <Lead>
        In Short: We may share information in specific situations described in this
        section and/or with the following third parties.
      </Lead>
      <P>
        <strong>Business Transfers.</strong> We may share or transfer your information
        in connection with, or during negotiations of, any merger, sale of company
        assets, financing, or acquisition of all or a portion of our business to
        another company.
      </P>

      <H2>5. Do We Use Cookies and Other Tracking Technologies?</H2>
      <Lead>
        In Short: We may use cookies and other tracking technologies to collect and
        store your information.
      </Lead>
      <P>
        We may use cookies and similar tracking technologies (like web beacons and
        pixels) to gather information when you interact with our Services. We also
        permit third parties and service providers to use online tracking technologies
        for analytics and advertising. We may share your information with Google
        Analytics to track and analyze the use of the Services. To opt out of being
        tracked by Google Analytics, visit https://tools.google.com/dlpage/gaoptout.
      </P>

      <H2>6. How Long Do We Keep Your Information?</H2>
      <Lead>
        In Short: We keep your information for as long as necessary to fulfill the
        purposes outlined in this Privacy Notice unless otherwise required by law.
      </Lead>
      <P>
        When we have no ongoing legitimate business need to process your personal
        information, we will either delete or anonymize such information, or, if this is
        not possible, securely store and isolate it from further processing until
        deletion is possible.
      </P>

      <H2>7. How Do We Keep Your Information Safe?</H2>
      <Lead>
        In Short: We aim to protect your personal information through a system of
        organizational and technical security measures.
      </Lead>
      <P>
        However, despite our safeguards, no electronic transmission over the Internet or
        information storage technology can be guaranteed to be 100% secure. You should
        only access the Services within a secure environment.
      </P>

      <H2>8. Do We Collect Information From Minors?</H2>
      <Lead>
        In Short: We do not knowingly collect data from or market to children under 18
        years of age or the equivalent age as specified by law in your jurisdiction.
      </Lead>
      <P>
        If we learn that personal information from users less than 18 years of age has
        been collected, we will deactivate the account and take reasonable measures to
        promptly delete such data. If you become aware of any data we may have collected
        from children under age 18, please contact us at info@futureform.com.
      </P>

      <H2>9. What Are Your Privacy Rights?</H2>
      <Lead>
        In Short: Depending on your state or region of residence, you may have rights
        that allow you greater access to and control over your personal information.
      </Lead>
      <P>
        These may include the right to request access, rectification or erasure, to
        restrict processing, to data portability, and not to be subject to automated
        decision-making. To exercise these rights, contact us using the details below.
        If you have questions about your privacy rights, you may email us at
        info@futureform.com.
      </P>

      <H2>10. Controls for Do-Not-Track Features</H2>
      <P>
        Most web browsers include a Do-Not-Track (“DNT”) feature. At this stage, no
        uniform technology standard for recognizing and implementing DNT signals has
        been finalized, so we do not currently respond to DNT browser signals.
      </P>

      <H2>11. Do United States Residents Have Specific Privacy Rights?</H2>
      <Lead>
        In Short: If you are a resident of certain US states, you may have the right to
        request access to and receive details about the personal information we maintain
        about you, correct inaccuracies, get a copy of, or delete your personal
        information.
      </Lead>
      <P>
        These rights include the right to know whether we are processing your personal
        data, to access it, to correct inaccuracies, to request deletion, to obtain a
        copy, to non-discrimination for exercising your rights, and to opt out of
        processing for targeted advertising or sale. To exercise these rights, you can
        contact us by submitting a data subject access request, by calling toll-free at
        800-869-7222, or by referring to the contact details below.
      </P>

      <H2>12. Do We Make Updates to This Notice?</H2>
      <Lead>In Short: Yes, we will update this notice as necessary to stay compliant with relevant laws.</Lead>
      <P>
        The updated version will be indicated by an updated “Revised” date. We encourage
        you to review this Privacy Notice frequently to be informed of how we are
        protecting your information.
      </P>

      <H2>13. How Can You Contact Us About This Notice?</H2>
      <P>
        If you have questions or comments about this notice, you may email us at
        info@futureform.com or contact us by post at:
      </P>
      <P>
        Future Form Manufacturing LLC.
        <br />
        599 East Nugget Ave
        <br />
        Sparks, NV 89431-5702
        <br />
        United States
      </P>

      <H2>14. How Can You Review, Update, or Delete the Data We Collect From You?</H2>
      <P>
        Based on the applicable laws of your country or state of residence, you may have
        the right to request access to the personal information we collect from you,
        details about how we have processed it, correct inaccuracies, or delete your
        personal information. To request to review, update, or delete your personal
        information, please submit a data subject access request or contact us at
        info@futureform.com.
      </P>
    </LegalLayout>
  )
}
