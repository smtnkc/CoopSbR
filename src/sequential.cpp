#include "coopsbr/solver.hpp"
#include <algorithm>
#include <chrono>
#include <stdexcept>
namespace coopsbr {
using Clock=std::chrono::steady_clock;
static double ms(Clock::time_point a,Clock::time_point b) { return std::chrono::duration<double,std::milli>(b-a).count(); }
Result solve_seq(const std::vector<int>& input,const Options& options) {
    auto begin=Clock::now();
    int n=static_cast<int>(input.size()), size=n+2;
    std::vector<int> p(size),pos(size);
    std::vector<Reversal> trace(n+1);
    p[0]=0; p[n+1]=n+1;
    std::copy(input.begin(),input.end(),p.begin()+1);
    Result result;
    result.sorted.resize(n);
    result.allocated_bytes=2ULL*size*sizeof(int)+(n+1ULL)*sizeof(Reversal)+n*sizeof(int);
    auto start=Clock::now();
    result.allocation_ms=ms(begin,start);
    for(int i=0;i<size;++i) pos[p[i]]=i;
    int count=0;
    Summary previous; bool have_previous=false;
    while(true) {
        Summary s;
        result.summary_elements+=size;
        for(int i=0;i<size;++i) s=combine(s,leaf(p.data(),size,i));
        if(count==0) result.initial_breakpoints=s.breakpoints;
        if(options.debug && have_previous) {
            bool good=previous.decreasing ? s.breakpoints<previous.breakpoints :
                      s.breakpoints==previous.breakpoints && s.decreasing>0;
            if(previous.decreasing && s.decreasing==0 && s.breakpoints>0)
                good=good && s.breakpoints<=previous.breakpoints-2;
            if(!good) throw std::runtime_error("Decision policy progress invariant failed");
            for(int i=0;i<size;++i) if(pos[p[i]]!=i) throw std::runtime_error("Position invariant failed");
        }
        if(s.breakpoints==0) break;
        Reversal r;
        if(s.decreasing==0) r={s.first,s.second-1};
        else {
            r=minimum_reversal(s,pos.data());
            bool has_decreasing=false;
            for(int i=1;i<size-1;++i) {
                ++result.candidate_elements;
                if(decreasing_at(p.data(),size,i,r)) { has_decreasing=true; break; }
            }
            if(!has_decreasing) r=maximum_reversal(s,pos.data());
        }
        if(!valid(r,size) || count>=n+1) throw std::runtime_error("Invalid reversal or termination bound exceeded");
        trace[count++]={r.left-1,r.right-1};
        std::reverse(p.begin()+r.left,p.begin()+r.right+1);
        for(int i=r.left;i<=r.right;++i) pos[p[i]]=i;
        result.updated_elements+=r.right-r.left+1;
        previous=s; have_previous=true;
    }
    if(count>result.initial_breakpoints) throw std::runtime_error("Breakpoint solution-length bound failed");
    auto end=Clock::now();
    result.sort_ms=ms(start,end);
    std::copy(p.begin()+1,p.end()-1,result.sorted.begin());
    trace.resize(count); result.trace=std::move(trace);
    std::vector<int>().swap(p);std::vector<int>().swap(pos);
    result.end_to_end_ms=ms(begin,Clock::now());
    return result;
}
}
