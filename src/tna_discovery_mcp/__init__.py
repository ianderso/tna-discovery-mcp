"""An MCP server for Discovery, the catalogue of the UK National Archives.

Discovery describes the records The National Archives holds at Kew, and the
catalogues of more than 2,500 other archives, through a keyless JSON API. The
server searches those descriptions, reads one with its place in the
hierarchy, walks down a series or a piece, and finds a soldier's discharge
papers in WO 97 by name, regiment, birthplace and dates. It keeps no copy of
anything the API returns, as the API's terms ask, and holds itself to TNA's
guideline of one request a second and 3,000 a day. Nothing here writes
anywhere, and nothing here keeps a family tree.
"""

__version__ = "0.1.0"
