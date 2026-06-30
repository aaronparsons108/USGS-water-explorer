import pandas as pd
import dataretrieval as nwis
from IPython.display import display #Doing display(obj) rather than print(obj)



pmcode = "99133"
#start_date = "2008-01-01" #end_date = "____-__-__"

all_sites = []
output_path = (f"{pmcode}_data.csv")
states = [
        "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
        "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
        "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
        "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
        "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    ]


print(f"Starting retrieval for parameter {pmcode}...")
for st in states:
    try:
        sites, _ = nwis.get_info(stateCd = st, parameterCd = pmcode, seriesCatalogOutput = True)
        if not sites.empty:
            sites = sites[sites["parm_cd"] == pmcode]
            sites = sites[sites["data_type_cd"] == "dv"]
            #sites = sites[sites["begin_date"] >= start_date]
            sites = sites[sites["site_no"].str.len() != 15] #No 15 number sites (wells)
            all_sites.append(sites)
            print(f"{st}: Found {len(sites)} sites.")
        else:
            print(f"{st}: No sites found.")
    except Exception as e:
        print(f"{st}: failed ({e})")
sites = pd.concat(all_sites, ignore_index=True)


# 3. Combine and Export
if all_sites:
    sites_final = pd.concat(all_sites, ignore_index=True)
    sites_final.to_csv(output_path, index=False)
    print(f"--- Success! Saved {len(sites_final)} total sites to {output_path} ---")
    display(sites_final.head())
else:
    print("No data was collected.")
