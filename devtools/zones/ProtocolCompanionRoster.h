#ifndef INCLUDED_ProtocolCompanionRoster_H
#define INCLUDED_ProtocolCompanionRoster_H
#include <map>
#include <set>
#include <string>
// Explicit fixture identities only; no arbitrary name/ID target is accepted.
class ProtocolCompanionRoster
{
public:
    bool add(std::string const &id,std::string const &name)
    {
        if(m_ids.size()>=31 || id.empty() || id.size()>19 || id[0]<'1' || id[0]>'9' ||
           id.find_first_not_of("0123456789")!=std::string::npos || (id.size()==19 && id>"9223372036854775807") ||
           name.size()!=15 || name.substr(0,3)!="Cap" || name.substr(3).find_first_not_of("abcdefghijklmnopqrstuvwxyz")!=std::string::npos ||
           m_ids.count(id) || m_names.count(name)) return false;
        m_ids[id]=name;m_names.insert(name);return true;
    }
    std::string const *find(std::string const &id) const
    { std::map<std::string,std::string>::const_iterator i=m_ids.find(id);return i==m_ids.end()?0:&i->second; }
private:
    std::map<std::string,std::string> m_ids;std::set<std::string> m_names;
};
#endif
