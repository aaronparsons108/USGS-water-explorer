import pandas as pd
from dataretrieval import nwis
print(dir(nwis))
print("\n---get_dv help---\n")
help(nwis.get_dv)
#['ALLPARAMCODES_URL', 'BaseMetadata', 'List', 'NWIS_Metadata', 'Optional', 'PARAMCODES_URL', 'StringIO', 'Tuple', 'Union', 'WATERDATA_BASE_URL', 'WATERDATA_SERVICES', 'WATERDATA_URL', 'WATERSERVICES_SERVICES', 'WATERSERVICE_URL', '_CRS', '__builtins__', '__cached__', '__doc__', '__file__', '__loader__', '__name__', '__package__', '__spec__', '_check_sites_value_types', '_read_json', '_read_rdb', 'format_datetime', 'format_response', 'get_discharge_measurements', 'get_discharge_peaks', 'get_dv', 'get_gwlevels', 'get_info', 'get_iv', 'get_pmcodes', 'get_qwdata', 'get_ratings', 'get_record', 'get_stats', 'get_water_use', 'gpd', 'pd', 'preformat_peaks_response', 'query', 'query_waterdata', 'query_waterservices', 're', 'requests', 'warnings', 'what_sites']
print("\n---get_info help---\n")
help(nwis.get_info)