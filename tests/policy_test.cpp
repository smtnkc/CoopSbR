#include "coopsbr/solver.hpp"
#include <algorithm>
#include <cstdint>
#include <iostream>
#include <numeric>
#include <stdexcept>
#include <unordered_map>
#include <vector>
using namespace coopsbr;
static void require(bool b,const char* s) { if(!b) throw std::runtime_error(s); }
static std::uint64_t encode(const std::vector<int>& p) {
    std::uint64_t x=0;for(std::size_t i=0;i<p.size();++i) x|=std::uint64_t(p[i])<<(4*i);return x;
}
static std::vector<int> decode(std::uint64_t x,int n) {
    std::vector<int> p(n);for(int i=0;i<n;++i) p[i]=(x>>(4*i))&15;return p;
}
// Separate maximal-strip traversal, intentionally independent of leaf().
static Summary strips(const std::vector<int>& p) {
    Summary s;int size=static_cast<int>(p.size());
    for(int l=0;l<size;) {
        int r=l;
        while(r+1<size && std::abs(p[r+1]-p[r])==1) ++r;
        if(l>0) { if(s.breakpoints==0)s.first=l;else if(s.breakpoints==1)s.second=l;++s.breakpoints; }
        bool dec=r>l ? p[l]>p[r] : l>0 && r<size-1;
        if(dec) for(int i=l;i<=r;++i) {
            s.minimum=std::min(s.minimum,p[i]);s.maximum=std::max(s.maximum,p[i]);++s.decreasing;
        }
        l=r+1;
    }
    return s;
}
int main(int argc,char** argv) {
    try {
        int limit=argc==2?std::stoi(argv[1]):8;
        require(limit>=1 && limit<=8,"Exact test limit must be 1..8");
        std::uint64_t tested=0, equal_witnesses=0, distinct_witnesses=0;
        for(int n=1;n<=limit;++n) {
            std::vector<int> id(n);std::iota(id.begin(),id.end(),1);
            std::unordered_map<std::uint64_t,int> distance;
            std::vector<std::uint64_t> queue{encode(id)};distance[queue[0]]=0;
            for(std::size_t head=0;head<queue.size();++head) {
                auto p=decode(queue[head],n);int d=distance.at(queue[head]);
                for(int l=0;l<n;++l) for(int r=l+1;r<n;++r) {
                    std::reverse(p.begin()+l,p.begin()+r+1);
                    auto code=encode(p);
                    if(distance.emplace(code,d+1).second) queue.push_back(code);
                    std::reverse(p.begin()+l,p.begin()+r+1);
                }
            }
            for(auto code:queue) {
                auto p=decode(code,n);auto padded=p;padded.insert(padded.begin(),0);padded.push_back(n+1);
                Summary expected=strips(padded),actual;
                std::vector<int> pos(n+2);
                for(int i=0;i<n+2;++i) {actual=combine(actual,leaf(padded.data(),n+2,i));pos[padded[i]]=i;}
                require(equal(actual,expected),"Local membership differs from independent strip traversal");
                if(expected.decreasing) {
                    auto a=minimum_reversal(expected,pos.data()),b=maximum_reversal(expected,pos.data());
                    require(valid(a,n+2)&&valid(b,n+2),"Invalid extremal witness");
                    auto pa=padded,pb=padded;
                    std::reverse(pa.begin()+a.left,pa.begin()+a.right+1);
                    std::reverse(pb.begin()+b.left,pb.begin()+b.right+1);
                    auto sa=strips(pa),sb=strips(pb);
                    require(sa.breakpoints<expected.breakpoints && sb.breakpoints<expected.breakpoints,"Extremal witness does not remove a breakpoint");
                    if(sa.decreasing==0 && sb.decreasing==0) {
                        require(sb.breakpoints==expected.breakpoints-2,"Two-witness reduction condition failed");
                        int left=pos[expected.minimum-1], low=pos[expected.minimum];
                        int high=pos[expected.maximum], right=pos[expected.maximum+1];
                        require(left<low && high<right,"No-decreasing witness orientation failed");
                        require(high==left+1 || high==left+2,"Left fringe width proof failed");
                        require(right==low+1 || right==low+2,"Right fringe width proof failed");
                        if(high==left+1) {
                            require(right==low+1,"Empty-left/nonempty-right fringe should be impossible");
                            ++equal_witnesses;
                        } else {
                            require(padded[right-1]==padded[high-1]+1,"Second repaired adjacency proof failed");
                            ++distinct_witnesses;
                        }
                    }
                }
                Options options;options.debug=true;
                auto result=solve_seq(p,options);
                require(result.trace.size()<=2ULL*distance.at(code),"2-approximation check failed");
                require(result.trace.size()<=static_cast<std::size_t>(expected.breakpoints),"Breakpoint budget failed");
                auto state=padded;
                auto before=strips(state);
                if(before.breakpoints>0 && before.decreasing>0)
                    require(result.trace.size()<static_cast<std::size_t>(before.breakpoints),"Refined potential bound failed");
                for(std::size_t step=0;step<result.trace.size();++step) {
                    auto r=result.trace[step];
                    require(r.left>=0 && r.left<r.right && r.right<n,"Invalid returned endpoint");
                    std::reverse(p.begin()+r.left,p.begin()+r.right+1);
                    std::reverse(state.begin()+r.left+1,state.begin()+r.right+2);
                    auto after=strips(state);
                    int phi_before=before.breakpoints+(before.breakpoints>0 && before.decreasing==0);
                    int phi_after=after.breakpoints+(after.breakpoints>0 && after.decreasing==0);
                    require(phi_before-phi_after>=1,"Potential decrease failed");
                    if(before.decreasing==0)
                        require(after.breakpoints==before.breakpoints && after.decreasing>0,"Zero-drop strip flip proof failed");
                    if(step+1==result.trace.size()) require(phi_before-phi_after>=2,"Terminal potential saving failed");
                    before=after;
                }
                require(p==id && result.sorted==id,"Independent replay failed");++tested;
            }
            std::cout<<"n="<<n<<" permutations="<<queue.size()<<" PASS\n";
        }
        require(limit<6 || distinct_witnesses>0,"Missing unequal-witness regression coverage");
        std::cout<<"witness cases: equal="<<equal_witnesses<<" distinct="<<distinct_witnesses<<'\n';
        std::cout<<"PASS exact permutations="<<tested<<'\n';
    } catch(const std::exception& e) { std::cerr<<e.what()<<'\n';return 1; }
}
