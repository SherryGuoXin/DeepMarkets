from __future__ import annotations

import unittest

from etl.research_13dg_people import filing_url, parse_schedule_xml


SCHEDULE_XML = b"""<?xml version="1.0"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/schedule13g">
  <headerData><filerInfo><filer><filerCredentials>
    <cik>0001536411</cik>
  </filerCredentials></filer></filerInfo></headerData>
  <formData>
    <coverPageHeader>
      <eventDateRequiresFilingThisStatement>06/30/2026</eventDateRequiresFilingThisStatement>
      <issuerInfo><issuerCik>0001978954</issuerCik><issuerName>BBB Foods Inc</issuerName>
        <issuerCusips><issuerCusipNumber>G0896C103</issuerCusipNumber></issuerCusips>
      </issuerInfo>
    </coverPageHeader>
    <coverPageHeaderReportingPersonDetails>
      <reportingPersonName>Duquesne Family Office LLC</reportingPersonName>
      <typeOfReportingPerson>CO</typeOfReportingPerson>
    </coverPageHeaderReportingPersonDetails>
    <coverPageHeaderReportingPersonDetails>
      <reportingPersonName>Stanley Druckenmiller</reportingPersonName>
      <reportingPersonBeneficiallyOwnedAggregateNumberOfShares>2901733</reportingPersonBeneficiallyOwnedAggregateNumberOfShares>
      <classPercent>3.7</classPercent><typeOfReportingPerson>IN</typeOfReportingPerson>
    </coverPageHeaderReportingPersonDetails>
    <signatureInformation><reportingPersonName>Stanley Druckenmiller</reportingPersonName>
      <signatureDetails><title>Chairman and CEO</title></signatureDetails>
    </signatureInformation>
  </formData>
</edgarSubmission>"""


class ScheduleResearchTest(unittest.TestCase):
    def test_modern_schedule_xml_extracts_only_individuals(self) -> None:
        result = parse_schedule_xml(SCHEDULE_XML)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["filer_cik"], "0001536411")
        self.assertEqual(result["issuer_cik"], "0001978954")
        self.assertEqual(result["cusip"], "G0896C103")
        self.assertEqual(result["reporting_names"], "Duquesne Family Office LLC; Stanley Druckenmiller")
        self.assertEqual(
            result["people"],
            [{
                "person_name": "Stanley Druckenmiller",
                "reporting_person_type": "IN",
                "role": "Chairman and CEO",
                "shares_beneficially_owned": "2901733",
                "ownership_percent": "3.7",
            }],
        )

    def test_xsl_prefix_is_removed_from_archive_document_url(self) -> None:
        self.assertEqual(
            filing_url(
                "0001536411", "0000899140-26-000744",
                "xslSCHEDULE_13G_X02/primary_doc.xml",
            ),
            "https://www.sec.gov/Archives/edgar/data/1536411/"
            "000089914026000744/primary_doc.xml",
        )


if __name__ == "__main__":
    unittest.main()
