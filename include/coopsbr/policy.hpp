#pragma once
#include <climits>
#ifdef __CUDACC__
#define CS_HD __host__ __device__
#else
#define CS_HD
#endif
namespace coopsbr {
struct Reversal { int left = 0, right = -1; };
struct Summary {
    int minimum = INT_MAX, maximum = 0, decreasing = 0;
    int breakpoints = 0, first = INT_MAX, second = INT_MAX;
};
CS_HD inline int imin(int a, int b) { return a < b ? a : b; }
CS_HD inline int imax(int a, int b) { return a > b ? a : b; }
CS_HD inline bool adjacent(int a, int b) { return a-b == 1 || b-a == 1; }
CS_HD inline Summary combine(Summary a, Summary b) {
    Summary s;
    s.minimum=imin(a.minimum,b.minimum); s.maximum=imax(a.maximum,b.maximum);
    s.decreasing=a.decreasing+b.decreasing; s.breakpoints=a.breakpoints+b.breakpoints;
    if (a.first < b.first) { s.first=a.first; s.second=imin(a.second,b.first); }
    else { s.first=b.first; s.second=imin(b.second,a.first); }
    return s;
}
CS_HD inline int viewed(const int* p, int i, Reversal r) {
    return p[i>=r.left && i<=r.right ? r.left+(r.right-i) : i];
}
CS_HD inline bool decreasing_neighbors(int a,int v,int b) {
    return a==v+1 || b==v-1 || (!adjacent(a,v) && !adjacent(v,b));
}
CS_HD inline bool decreasing_at(const int* p, int size, int i, Reversal r = {}) {
    if (i==0 || i==size-1) return false;
    int v=viewed(p,i,r), a=viewed(p,i-1,r), b=viewed(p,i+1,r);
    return decreasing_neighbors(a,v,b);
}
CS_HD inline Summary leaf(const int* p, int size, int i) {
    Summary s;
    if (decreasing_at(p,size,i)) { s.minimum=s.maximum=p[i]; s.decreasing=1; }
    if (i>0 && !adjacent(p[i-1],p[i])) { s.breakpoints=1; s.first=i; }
    return s;
}
CS_HD inline Summary virtual_leaf(const int* p, int size, int i, Reversal r) {
    Summary s;
    int value=viewed(p,i,r);
    bool left_break=i>0 && !adjacent(viewed(p,i-1,r),value);
    if (left_break) { s.breakpoints=1; s.first=i; }
    if (i>0 && i<size-1) {
        int left=viewed(p,i-1,r),right=viewed(p,i+1,r);
        if (decreasing_neighbors(left,value,right)) {
            s.minimum=s.maximum=value;
            s.decreasing=1;
        }
    }
    return s;
}
CS_HD inline bool equal(Summary a, Summary b) {
    return a.minimum==b.minimum && a.maximum==b.maximum && a.decreasing==b.decreasing &&
           a.breakpoints==b.breakpoints && a.first==b.first && a.second==b.second;
}
CS_HD inline Reversal minimum_reversal(Summary s, const int* pos) {
    int a=pos[s.minimum-1], b=pos[s.minimum];
    return {imin(a,b)+1,imax(a,b)};
}
CS_HD inline Reversal maximum_reversal(Summary s, const int* pos) {
    int a=pos[s.maximum], b=pos[s.maximum+1];
    return {imin(a,b),imax(a,b)-1};
}
CS_HD inline bool valid(Reversal r, int size) { return r.left>=1 && r.right<size-1 && r.left<r.right; }
}
