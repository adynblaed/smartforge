import { createFileRoute } from "@tanstack/react-router"

import { H2, LegalLayout, P, UL } from "@/components/Common/LegalLayout"

export const Route = createFileRoute("/terms")({
  component: TermsPage,
  head: () => ({ meta: [{ title: "Terms & Conditions - Future Form Manufacturing" }] }),
})

function TermsPage() {
  return (
    <LegalLayout title="Terms and Conditions" updated="March 27, 2026">
      <H2>Agreement to Our Legal Terms</H2>
      <P>
        We are Future Form Manufacturing LLC. (“Company,” “we,” “us,” “our”), a company
        registered in Nevada, United States at 599 East Nugget Ave, Sparks, NV 89431. We
        operate the website https://futureform.com (the “Site”), as well as any other
        related products and services that refer or link to these legal terms (the “Legal
        Terms”) (collectively, the “Services”).
      </P>
      <P>
        You can contact us by phone at (+1)7753583663, email at info@futureform.com, or
        by mail to 599 East Nugget Ave, Sparks, NV 89431, United States.
      </P>
      <P>
        These Legal Terms constitute a legally binding agreement made between you and
        Future Form Manufacturing LLC. concerning your access to and use of the Services.
        You agree that by accessing the Services, you have read, understood, and agreed
        to be bound by all of these Legal Terms. IF YOU DO NOT AGREE WITH ALL OF THESE
        LEGAL TERMS, THEN YOU ARE EXPRESSLY PROHIBITED FROM USING THE SERVICES AND YOU
        MUST DISCONTINUE USE IMMEDIATELY.
      </P>
      <P>
        We reserve the right, in our sole discretion, to make changes or modifications to
        these Legal Terms at any time and for any reason. We will alert you about any
        changes by updating the “Last updated” date of these Legal Terms. All users who
        are minors in the jurisdiction in which they reside (generally under the age of
        18) must have the permission of, and be directly supervised by, their parent or
        guardian to use the Services.
      </P>

      <H2>Table of Contents</H2>
      <UL
        items={[
          "1. Our Services",
          "2. Intellectual Property Rights",
          "3. User Representations",
          "4. Prohibited Activities",
          "5. User Generated Contributions",
          "6. Contribution License",
          "7. Services Management",
          "8. Privacy Policy",
          "9. Term and Termination",
          "10. Modifications and Interruptions",
          "11. Governing Law",
          "12. Dispute Resolution",
          "13. Corrections",
          "14. Disclaimer",
          "15. Limitations of Liability",
          "16. Indemnification",
          "17. User Data",
          "18. Electronic Communications, Transactions, and Signatures",
          "19. California Users and Residents",
          "20. Miscellaneous",
          "21. Contact Us",
        ]}
      />

      <H2>1. Our Services</H2>
      <P>
        The information provided when using the Services is not intended for distribution
        to or use by any person or entity in any jurisdiction or country where such
        distribution or use would be contrary to law or regulation. Those persons who
        choose to access the Services from other locations do so on their own initiative
        and are solely responsible for compliance with local laws. The Services are not
        tailored to comply with industry-specific regulations (HIPAA, FISMA, etc.).
      </P>

      <H2>2. Intellectual Property Rights</H2>
      <P>
        We are the owner or the licensee of all intellectual property rights in our
        Services, including all source code, databases, functionality, software, website
        designs, audio, video, text, photographs, and graphics in the Services (the
        “Content”), as well as the trademarks, service marks, and logos contained therein
        (the “Marks”). The Content and Marks are provided “AS IS” for your personal,
        non-commercial use or internal business purpose only.
      </P>
      <P>
        Subject to your compliance with these Legal Terms, we grant you a non-exclusive,
        non-transferable, revocable license to access the Services and download or print a
        copy of any portion of the Content to which you have properly gained access,
        solely for your personal, non-commercial use or internal business purpose. By
        sending us any Submissions, you agree to assign to us all intellectual property
        rights in such Submission.
      </P>

      <H2>3. User Representations</H2>
      <P>
        By using the Services, you represent and warrant that: (1) you have the legal
        capacity and you agree to comply with these Legal Terms; (2) you are not a minor
        in the jurisdiction in which you reside, or if a minor, you have received parental
        permission to use the Services; (3) you will not access the Services through
        automated or non-human means; (4) you will not use the Services for any illegal or
        unauthorized purpose; and (5) your use of the Services will not violate any
        applicable law or regulation.
      </P>

      <H2>4. Prohibited Activities</H2>
      <P>
        You may not access or use the Services for any purpose other than that for which we
        make the Services available. As a user of the Services, you agree not to, among
        other things:
      </P>
      <UL
        items={[
          "Systematically retrieve data to create or compile a collection, compilation, database, or directory without written permission.",
          "Trick, defraud, or mislead us and other users.",
          "Circumvent, disable, or otherwise interfere with security-related features of the Services.",
          "Use any information obtained from the Services to harass, abuse, or harm another person.",
          "Make improper use of our support services or submit false reports of abuse or misconduct.",
          "Upload or transmit viruses, Trojan horses, or other malicious material.",
          "Engage in any automated use of the system, such as scripts, data mining, robots, or scraping tools.",
          "Attempt to impersonate another user or person.",
          "Interfere with, disrupt, or create an undue burden on the Services.",
          "Copy or adapt the Services’ software, or decipher, decompile, disassemble, or reverse engineer it.",
          "Use the Services as part of any effort to compete with us or for any revenue-generating endeavor not endorsed by us.",
        ]}
      />

      <H2>5. User Generated Contributions</H2>
      <P>The Services do not offer users the ability to submit or post content.</P>

      <H2>6. Contribution License</H2>
      <P>
        You and the Services agree that we may access, store, process, and use any
        information and personal data that you provide and your choices (including
        settings). By submitting suggestions or other feedback regarding the Services, you
        agree that we can use and share such feedback for any purpose without compensation
        to you.
      </P>

      <H2>7. Services Management</H2>
      <P>
        We reserve the right, but not the obligation, to monitor the Services for
        violations of these Legal Terms, take appropriate legal action against anyone who
        violates the law or these Legal Terms, refuse or restrict access to the Services,
        and otherwise manage the Services in a manner designed to protect our rights and
        property and to facilitate the proper functioning of the Services.
      </P>

      <H2>8. Privacy Policy</H2>
      <P>
        We care about data privacy and security. By using the Services, you agree to be
        bound by our Privacy Policy, which is incorporated into these Legal Terms. The
        Services are hosted in the United States. If you access the Services from another
        region, you are transferring your data to the United States, and you expressly
        consent to have your data transferred to and processed in the United States.
      </P>

      <H2>9. Term and Termination</H2>
      <P>
        These Legal Terms shall remain in full force and effect while you use the Services.
        WE RESERVE THE RIGHT TO, IN OUR SOLE DISCRETION AND WITHOUT NOTICE OR LIABILITY,
        DENY ACCESS TO AND USE OF THE SERVICES TO ANY PERSON FOR ANY REASON. If we
        terminate or suspend your account, you are prohibited from registering and creating
        a new account.
      </P>

      <H2>10. Modifications and Interruptions</H2>
      <P>
        We reserve the right to change, modify, or remove the contents of the Services at
        any time or for any reason at our sole discretion without notice. We cannot
        guarantee the Services will be available at all times. You agree that we have no
        liability whatsoever for any loss, damage, or inconvenience caused by your
        inability to access or use the Services during any downtime or discontinuance.
      </P>

      <H2>11. Governing Law</H2>
      <P>
        These Legal Terms and your use of the Services are governed by and construed in
        accordance with the laws of the State of Nevada applicable to agreements made and
        to be entirely performed within the State of Nevada, without regard to its
        conflict of law principles.
      </P>

      <H2>12. Dispute Resolution</H2>
      <P>
        The parties agree to first attempt to negotiate any Dispute informally for at least
        thirty (30) days before initiating arbitration. If the parties are unable to
        resolve a Dispute through informal negotiations, the Dispute will be finally and
        exclusively resolved by binding arbitration under the Commercial Arbitration Rules
        of the American Arbitration Association. The arbitration will take place in Nevada.
        Any arbitration shall be limited to the Dispute between the parties individually;
        class actions are not permitted.
      </P>

      <H2>13. Corrections</H2>
      <P>
        There may be information on the Services that contains typographical errors,
        inaccuracies, or omissions, including descriptions, pricing, and availability. We
        reserve the right to correct any errors and to change or update the information on
        the Services at any time, without prior notice.
      </P>

      <H2>14. Disclaimer</H2>
      <P>
        THE SERVICES ARE PROVIDED ON AN AS-IS AND AS-AVAILABLE BASIS. YOU AGREE THAT YOUR
        USE OF THE SERVICES WILL BE AT YOUR SOLE RISK. TO THE FULLEST EXTENT PERMITTED BY
        LAW, WE DISCLAIM ALL WARRANTIES, EXPRESS OR IMPLIED, IN CONNECTION WITH THE
        SERVICES AND YOUR USE THEREOF, INCLUDING THE IMPLIED WARRANTIES OF MERCHANTABILITY,
        FITNESS FOR A PARTICULAR PURPOSE, AND NON-INFRINGEMENT.
      </P>

      <H2>15. Limitations of Liability</H2>
      <P>
        IN NO EVENT WILL WE OR OUR DIRECTORS, EMPLOYEES, OR AGENTS BE LIABLE TO YOU OR ANY
        THIRD PARTY FOR ANY DIRECT, INDIRECT, CONSEQUENTIAL, EXEMPLARY, INCIDENTAL,
        SPECIAL, OR PUNITIVE DAMAGES, INCLUDING LOST PROFIT, LOST REVENUE, LOSS OF DATA, OR
        OTHER DAMAGES ARISING FROM YOUR USE OF THE SERVICES.
      </P>

      <H2>16. Indemnification</H2>
      <P>
        You agree to defend, indemnify, and hold us harmless, including our subsidiaries,
        affiliates, and all of our respective officers, agents, partners, and employees,
        from and against any loss, damage, liability, claim, or demand, including
        reasonable attorneys’ fees and expenses, made by any third party due to or arising
        out of your use of the Services or breach of these Legal Terms.
      </P>

      <H2>17. User Data</H2>
      <P>
        We will maintain certain data that you transmit to the Services for the purpose of
        managing the performance of the Services, as well as data relating to your use of
        the Services. Although we perform regular routine backups of data, you are solely
        responsible for all data that you transmit or that relates to any activity you have
        undertaken using the Services.
      </P>

      <H2>18. Electronic Communications, Transactions, and Signatures</H2>
      <P>
        Visiting the Services, sending us emails, and completing online forms constitute
        electronic communications. You consent to receive electronic communications, and
        you agree that all agreements, notices, disclosures, and other communications we
        provide to you electronically satisfy any legal requirement that such communication
        be in writing. YOU HEREBY AGREE TO THE USE OF ELECTRONIC SIGNATURES, CONTRACTS,
        ORDERS, AND OTHER RECORDS.
      </P>

      <H2>19. California Users and Residents</H2>
      <P>
        If any complaint with us is not satisfactorily resolved, you can contact the
        Complaint Assistance Unit of the Division of Consumer Services of the California
        Department of Consumer Affairs in writing at 1625 North Market Blvd., Suite N 112,
        Sacramento, California 95834 or by telephone at (800) 952-5210 or (916) 445-1254.
      </P>

      <H2>20. Miscellaneous</H2>
      <P>
        These Legal Terms and any policies or operating rules posted by us constitute the
        entire agreement and understanding between you and us. Our failure to exercise or
        enforce any right or provision of these Legal Terms shall not operate as a waiver
        of such right or provision. If any provision or part of a provision of these Legal
        Terms is determined to be unlawful, void, or unenforceable, that provision is
        deemed severable and does not affect the validity and enforceability of any
        remaining provisions.
      </P>

      <H2>21. Contact Us</H2>
      <P>
        In order to resolve a complaint regarding the Services or to receive further
        information regarding use of the Services, please contact us at:
      </P>
      <P>
        Future Form Manufacturing LLC.
        <br />
        599 East Nugget Ave
        <br />
        Sparks, NV 89431
        <br />
        United States
        <br />
        Phone: (+1)7753583663
        <br />
        Fax: (+1)7753316312
        <br />
        info@futureform.com
      </P>
    </LegalLayout>
  )
}
